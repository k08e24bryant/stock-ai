"""Snapshot loader for record-oriented sources (corporate actions, dividends).

Purpose
    Load small, structured (JSON) development sources into their raw tables
    with the same guarantees as the daily-price loader
    (docs/data_sources/phase_2b_ingestion_design.md): deterministic snapshot
    identity, a database-free dry run by default, explicit revision
    confirmation, the source advisory lock, T0 registration plus an atomic T1,
    idempotent reruns, conflicts recorded (never overwritten), and provenance
    (file, record reference, run) on every row.

Inputs
    A `RecordSource` adapter (for example ``idx_bei_actions`` or
    ``idx_dividends``) and a snapshot directory containing ``manifest.json``.

Outputs
    A dry-run report (dict) or a `LoadResult`.

Assumptions
    * Data files are small (thousands of records), so each is parsed whole and
      rows are inserted in batches; no staging table is needed.
    * The security link is a **development heuristic**: a record's normalized
      ticker equals a source key of the price source. The table's
      ``security_match`` column records it; unmatched records keep
      ``security_id`` NULL. Records are never dropped for lack of a match.
    * The link is fixed when a row is first inserted; reruns never update it.

Limitations
    Development sources only; see requirements doc §36.

Example
    >>> from data.ingestion.records import normalize_ticker
    >>> normalize_ticker(" pPre ")
    'PPRE'
"""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any, Protocol

from sqlalchemy import Connection, Engine, Table, insert, select, text

from data.ingestion.loader import (
    Counters,
    IncidentDraft,
    LoaderBusyError,
    LoadFailedError,
    LoadNotConfirmedError,
    LoadResult,
    finish_run,
    insert_incident_drafts,
    mark_run_failed,
    register_snapshot,
    release_source_lock,
    snapshot_mismatch_incident,
    try_source_lock,
)
from data.ingestion.snapshot import (
    FileRole,
    InventoryEntry,
    SnapshotManifest,
    StructuralError,
    content_sha256,
    derive_snapshot_id,
    list_snapshot_files,
    read_bytes,
    sha256_hex,
)

_TICKER = re.compile(r"[A-Z0-9]+")
_INSERT_BATCH = 1000


def normalize_ticker(value: str) -> str | None:
    """Upper-case, trimmed ticker if it is a plain IDX code, else None."""
    ticker = value.strip().upper()
    return ticker if _TICKER.fullmatch(ticker) else None


def jsonable(value: Any) -> Any:
    """Recursively convert Decimals and dates to strings for JSONB details."""
    if isinstance(value, dict):
        return {str(k): jsonable(v) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [jsonable(v) for v in value]
    if isinstance(value, Decimal | date):
        return str(value)
    return value


# ============================================================ source protocol


@dataclass(frozen=True, slots=True)
class RecordResult:
    """One source record: normalized column values, or the reasons it has none."""

    record_ref: str
    values: dict[str, Any] | None
    match_key: str | None
    reasons: tuple[str, ...]
    raw: dict[str, Any]
    # Optional fields that could not be parsed: stored as NULL, raw value kept
    # in a ``malformed_optional_field`` incident (never repaired).
    issues: tuple[dict[str, Any], ...] = ()


class RecordSource(Protocol):
    """What a record-oriented source must provide to be loaded."""

    source_id: str
    source_name: str
    homepage_url: str | None
    parser_version: str
    table: Table
    natural_key: tuple[str, ...]
    observation: tuple[str, ...]
    date_column: str
    # True: rows carry ``security_id`` / ``security_match`` (ticker-text link).
    links_securities: bool
    # Provenance column of the table: ``record_ref`` (text) or ``source_line`` (int).
    provenance_column: str

    def read_manifest(self, root: Path) -> SnapshotManifest: ...

    def select_data_files(self, relative_paths: Sequence[str]) -> tuple[str, ...]:
        """The snapshot files holding records; raise `StructuralError` if absent."""
        ...

    def parse(self, relative_path: str, data: bytes) -> list[RecordResult]: ...


# ============================================================ pass 1 / pass 2


@dataclass(frozen=True, slots=True)
class PreparedRecordSnapshot:
    root: Path
    source: RecordSource
    manifest: SnapshotManifest
    entries: tuple[InventoryEntry, ...]
    content_sha256: str
    snapshot_id: str
    data_files: tuple[str, ...]


def prepare_record_snapshot(source: RecordSource, root: Path) -> PreparedRecordSnapshot:
    """Pass 1: inventory and identity; data files are parsed to count records."""
    manifest = source.read_manifest(root)
    if manifest.source_id != source.source_id:
        raise StructuralError(f"manifest is for {manifest.source_id!r}, not {source.source_id!r}")
    paths = list_snapshot_files(root)
    data_files = source.select_data_files(paths)
    if not data_files:
        raise StructuralError(f"no data files found under {root}")
    selected = set(data_files)
    entries: list[InventoryEntry] = []
    for rel in paths:
        data = read_bytes(root / rel)
        rows = len(source.parse(rel, data)) if rel in selected else 0
        entries.append(InventoryEntry(rel, sha256_hex(data), len(data), FileRole.OTHER, rows, None))
    content = content_sha256(entries)
    return PreparedRecordSnapshot(
        root=root,
        source=source,
        manifest=manifest,
        entries=tuple(entries),
        content_sha256=content,
        snapshot_id=derive_snapshot_id(source.source_id, manifest.revision, content),
        data_files=tuple(data_files),
    )


@dataclass(frozen=True, slots=True)
class ProcessedRecords:
    """Pass-2 result: accepted records (by natural key) and what was not accepted."""

    accepted: dict[tuple[Any, ...], tuple[str, RecordResult]]
    seen: int
    rejected: int
    collapsed: int
    incidents: tuple[IncidentDraft, ...]


def freeze(value: Any) -> Any:
    """Hashable, comparable form of a column value (arrays become tuples)."""
    return tuple(value) if isinstance(value, list) else value


def _observation(source: RecordSource, values: dict[str, Any]) -> tuple[Any, ...]:
    return tuple(freeze(values[c]) for c in source.observation)


def process_records(prepared: PreparedRecordSnapshot) -> ProcessedRecords:
    """Pass 2: re-read each data file, verify its hash, validate, de-duplicate."""
    source = prepared.source
    by_path = {e.relative_path: e for e in prepared.entries}
    incidents: list[IncidentDraft] = []
    seen = rejected = collapsed = 0
    groups: dict[tuple[Any, ...], list[tuple[str, RecordResult]]] = defaultdict(list)
    for rel in prepared.data_files:
        data = read_bytes(prepared.root / rel)
        if sha256_hex(data) != by_path[rel].sha256:
            raise StructuralError(f"{rel} changed since it was inventoried")
        for record in source.parse(rel, data):
            seen += 1
            if record.values is None:
                rejected += 1
                incidents.append(
                    IncidentDraft(
                        "hard_invalid_record",
                        "error",
                        record.match_key,
                        None,
                        rel,
                        None,
                        jsonable(
                            {
                                "record_ref": record.record_ref,
                                "reasons": list(record.reasons),
                                "raw": record.raw,
                            }
                        ),
                    )
                )
                continue
            key = tuple(record.values[c] for c in source.natural_key)
            groups[key].append((rel, record))
    accepted: dict[tuple[Any, ...], tuple[str, RecordResult]] = {}
    for key, members in groups.items():
        observations = {_observation(source, r.values or {}) for _, r in members}
        if len(observations) > 1:
            rejected += len(members)
            incidents.append(
                IncidentDraft(
                    "conflicting_duplicate_in_snapshot",
                    "error",
                    members[0][1].match_key,
                    None,
                    members[0][0],
                    None,
                    jsonable(
                        {
                            "natural_key": dict(zip(source.natural_key, key, strict=True)),
                            "record_refs": [r.record_ref for _, r in members],
                        }
                    ),
                )
            )
            continue
        accepted[key] = members[0]
        collapsed += len(members) - 1
        rel, kept = members[0]
        incidents.extend(
            IncidentDraft(
                "malformed_optional_field",
                "warning",
                kept.match_key,
                (kept.values or {}).get(source.date_column),
                rel,
                None,
                jsonable({"record_ref": kept.record_ref, **issue, "stored_as": None}),
            )
            for issue in kept.issues
        )
    return ProcessedRecords(accepted, seen, rejected, collapsed, tuple(incidents))


def dry_run_records(prepared: PreparedRecordSnapshot) -> dict[str, Any]:
    """Database-free report for a record snapshot (deterministic)."""
    processed = process_records(prepared)
    m = prepared.manifest
    match_keys = Counter(r.match_key is not None for _, r in processed.accepted.values())
    return {
        "mode": "dry_run",
        "identity": {
            "source_id": prepared.source.source_id,
            "source_revision": m.revision,
            "snapshot_id": prepared.snapshot_id,
            "content_sha256": prepared.content_sha256,
            "archive_sha256": m.archive_sha256,
            "retrieved_at": m.retrieved_at.isoformat(),
            "parser_version": prepared.source.parser_version,
            "files": len(prepared.entries),
        },
        "counters": {
            "records_seen": processed.seen,
            "records_accepted": len(processed.accepted),
            "records_rejected": processed.rejected,
            "records_collapsed_duplicates": processed.collapsed,
            "records_with_ticker": match_keys.get(True, 0),
            "records_without_ticker": match_keys.get(False, 0),
        },
        "incidents": sorted(
            (
                {
                    "type": i.incident_type,
                    "record": i.details.get("record_ref"),
                    "fp": i.fingerprint,
                }
                for i in processed.incidents
            ),
            key=lambda d: str(d["fp"]),
        ),
    }


def provenance_value(source: RecordSource, record_ref: str) -> dict[str, Any]:
    """The table's provenance column for a record (text ref or integer line)."""
    if source.provenance_column == "source_line":
        return {"source_line": int(record_ref)}
    return {"record_ref": record_ref}


# ============================================================ database load


class RecordLoader:
    """Loads a prepared record snapshot (see module docstring)."""

    def __init__(self, engine: Engine, *, price_source_id: str) -> None:
        self.engine = engine
        self.price_source_id = price_source_id

    def load(self, prepared: PreparedRecordSnapshot, *, confirm_revision: str) -> LoadResult:
        if confirm_revision != prepared.manifest.revision:
            raise LoadNotConfirmedError(
                f"confirm_revision {confirm_revision!r} does not match snapshot revision "
                f"{prepared.manifest.revision!r}; nothing was written"
            )
        src = prepared.source
        with self.engine.connect() as conn:
            if not try_source_lock(conn, src.source_id):
                raise LoaderBusyError(f"another ingestion for {src.source_id!r} is running")
            try:
                with conn.begin():
                    run_id, file_ids, mismatch_with = register_snapshot(
                        conn,
                        source_id=src.source_id,
                        source_name=src.source_name,
                        homepage_url=src.homepage_url,
                        parser_version=src.parser_version,
                        manifest=prepared.manifest,
                        entries=prepared.entries,
                        content_sha256=prepared.content_sha256,
                        snapshot_id=prepared.snapshot_id,
                        root=prepared.root,
                    )
                    t0_incidents = 0
                    if mismatch_with:
                        t0_incidents = insert_incident_drafts(
                            conn,
                            src.source_id,
                            run_id,
                            [
                                snapshot_mismatch_incident(
                                    prepared.manifest.revision,
                                    prepared.content_sha256,
                                    mismatch_with,
                                )
                            ],
                            security_ids={},
                            file_ids={},
                        )
                try:
                    with conn.begin():
                        counters, summary = self._load_records(conn, prepared, run_id, file_ids)
                        counters.incidents_created += t0_incidents
                        finish_run(conn, run_id, counters, summary)
                except Exception as exc:  # T1 already rolled back
                    with conn.begin():
                        mark_run_failed(conn, run_id, exc)
                    raise LoadFailedError(run_id, exc) from exc
                return LoadResult(run_id, prepared.snapshot_id, counters, summary)
            finally:
                release_source_lock(conn, src.source_id)

    def _load_records(
        self,
        conn: Connection,
        prepared: PreparedRecordSnapshot,
        run_id: Any,
        file_ids: dict[str, int],
    ) -> tuple[Counters, dict[str, Any]]:
        src = prepared.source
        processed = process_records(prepared)
        counters = Counters(
            rows_seen=processed.seen,
            rows_rejected=processed.rejected,
            rows_collapsed_duplicates=processed.collapsed,
            files_processed=len(prepared.data_files),
        )
        match_keys = sorted(
            {r.match_key for _, r in processed.accepted.values() if r.match_key is not None}
        )
        securities: dict[str, int] = {}
        if src.links_securities:
            securities = {
                key: int(sid)
                for key, sid in conn.execute(
                    text(
                        "SELECT source_key, security_id FROM security_source_keys "
                        "WHERE source_id = :src AND source_key = ANY(:keys)"
                    ),
                    {"src": self.price_source_id, "keys": match_keys},
                )
            }
        table = src.table
        key_cols = [table.c[c] for c in src.natural_key]
        obs_cols = [table.c[c] for c in src.observation]
        existing = {
            tuple(row[: len(key_cols)]): tuple(freeze(v) for v in row[len(key_cols) :])
            for row in conn.execute(
                select(*key_cols, *obs_cols).where(table.c.source_id == src.source_id)
            )
        }
        new_rows: list[dict[str, Any]] = []
        drafts = list(processed.incidents)
        for key in sorted(processed.accepted, key=repr):
            rel, record = processed.accepted[key]
            values = record.values or {}
            incoming = _observation(src, values)
            stored = existing.get(key)
            if stored is None:
                row: dict[str, Any] = {
                    **values,
                    "source_id": src.source_id,
                    "file_id": file_ids[rel],
                    "ingestion_run_id": run_id,
                    **provenance_value(src, record.record_ref),
                }
                if src.links_securities:
                    security_id = securities.get(record.match_key) if record.match_key else None
                    row["security_id"] = security_id
                    row["security_match"] = (
                        "unmatched" if security_id is None else "ticker_text_match"
                    )
                new_rows.append(row)
            elif stored == incoming:  # Decimal and date compare by value
                counters.rows_unchanged += 1
            else:
                counters.rows_conflicted += 1
                drafts.append(
                    IncidentDraft(
                        "conflicting_observation",
                        "error",
                        record.match_key,
                        values.get(src.date_column),
                        rel,
                        None,
                        jsonable(
                            {
                                "natural_key": dict(zip(src.natural_key, key, strict=True)),
                                "record_ref": record.record_ref,
                                "stored": dict(zip(src.observation, stored, strict=True)),
                                "incoming": dict(zip(src.observation, incoming, strict=True)),
                            }
                        ),
                    )
                )
        for start in range(0, len(new_rows), _INSERT_BATCH):
            conn.execute(insert(table), new_rows[start : start + _INSERT_BATCH])
        counters.rows_inserted = len(new_rows)
        counters.incidents_created += insert_incident_drafts(
            conn, src.source_id, run_id, drafts, security_ids=securities, file_ids=file_ids
        )
        counters.securities_resolved = len(securities)
        if not counters.consistent():
            raise RuntimeError(f"row counters are inconsistent: {asdict(counters)}")
        summary: dict[str, Any] = {
            "mode": "load",
            "source_id": src.source_id,
            "snapshot_id": prepared.snapshot_id,
            "parser_version": src.parser_version,
            "table": src.table.name,
        }
        if src.links_securities:
            summary["security_link"] = {
                "price_source_id": self.price_source_id,
                "method": "ticker_text_match (development heuristic)",
                "tickers_seen": len(match_keys),
                "tickers_matched": len(securities),
                "rows_inserted_unmatched": sum(1 for r in new_rows if r["security_id"] is None),
            }
        return counters, summary


__all__ = [
    "PreparedRecordSnapshot",
    "ProcessedRecords",
    "RecordLoader",
    "RecordResult",
    "RecordSource",
    "dry_run_records",
    "freeze",
    "jsonable",
    "normalize_ticker",
    "prepare_record_snapshot",
    "process_records",
    "provenance_value",
]
