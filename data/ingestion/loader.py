"""Provider-agnostic snapshot loader: inventory, dry run, and database load.

Purpose
    Implement docs/data_sources/phase_2b_ingestion_design.md for any source
    that supplies a `SnapshotSource` adapter (today: Pholenk).

Lifecycle
    1. ``prepare_snapshot`` (pass 1): read each file, hash those bytes,
       classify roles, inspect stock files, derive the snapshot identity. No
       database access. Structural problems raise `StructuralError`.
    2. ``dry_run``: pass 2 without a database; deterministic report.
    3. ``SnapshotLoader.load`` (requires an explicit revision confirmation):
       source advisory lock → T0 registration (snapshot, files, run; committed)
       → T1 atomic load (securities, streaming COPY into a temporary staging
       table, set-based classification new/unchanged/conflict, inserts,
       incidents, run marked succeeded). Any T1 failure rolls back every T1
       write and marks the run failed.

Outputs
    `PreparedSnapshot`, a dry-run report (dict), or a `LoadResult`.

Assumptions
    * Two passes, by design: for each pass, hashing and parsing use the same
      bytes. Pass 2 re-reads each stock file, re-hashes it before parsing, and
      fails if the bytes changed since pass 1.
    * Only one stock file is held in Python memory at a time.
    * Stored observations are never overwritten; differences become
      ``conflicting_observation`` incidents.

Limitations
    Development data only; no corporate actions or adjustments.

Example
    >>> Counters().consistent()
    True
"""

from __future__ import annotations

import hashlib
import json
import uuid
from collections import Counter, defaultdict
from collections.abc import Iterator, Sequence
from dataclasses import asdict, dataclass, field, fields
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any, Protocol

from sqlalchemy import Connection, Engine, select, text, update
from sqlalchemy.dialects.postgresql import insert as pg_insert

from backend.models import (
    DataQualityIncident,
    DataSource,
    IngestionRun,
    Security,
    SecuritySourceKey,
    SourceFile,
    SourceSnapshot,
)
from data.ingestion.provider import DailyPrice, PriceBasis, TradingStatus
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
from data.validation.daily_prices import Severity, validate_daily_price

FLAG_TICKER_COLUMN_MISMATCH = "source_ticker_column_mismatch"
STAGE_TABLE = "ingest_stage"
STAGE_COLUMNS = (
    "security_id",
    "trading_date",
    "open",
    "high",
    "low",
    "close",
    "reference_price",
    "volume",
    "value",
    "frequency",
    "trading_status",
    "quality_flags",
    "file_id",
    "source_line",
)
STAGE_TYPES = (
    "int8",
    "date",
    "numeric",
    "numeric",
    "numeric",
    "numeric",
    "numeric",
    "int8",
    "numeric",
    "int8",
    "text",
    "text[]",
    "int8",
    "int4",
)
OBSERVATION_COLUMNS = (
    "open",
    "high",
    "low",
    "close",
    "reference_price",
    "volume",
    "value",
    "frequency",
    "trading_status",
    "quality_flags",
)


# ============================================================ source protocol


@dataclass(frozen=True, slots=True)
class FileInspection:
    """Pass-1 facts about one file, taken from the bytes that were hashed."""

    row_count: int
    source_key: str | None = None
    newest_name: str | None = None
    newest_date: date | None = None
    ticker_mismatch_values: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class RowResult:
    """One source data line: a normalized price, or the reasons it was not."""

    line: int
    price: DailyPrice | None
    cells: tuple[str, ...]
    reasons: tuple[str, ...]


class SnapshotSource(Protocol):
    """What a source must provide to be loaded."""

    source_id: str
    source_name: str
    homepage_url: str | None
    parser_version: str

    def read_manifest(self, root: Path) -> SnapshotManifest: ...

    def classify(self, relative_path: str) -> FileRole: ...

    def inspect(self, relative_path: str, data: bytes, role: FileRole) -> FileInspection: ...

    def iter_rows(
        self, relative_path: str, data: bytes, file_sha256: str, manifest: SnapshotManifest
    ) -> Iterator[RowResult]: ...


# ============================================================ errors


class LoadNotConfirmedError(RuntimeError):
    """A database load was requested without confirming the exact revision."""


class LoaderBusyError(RuntimeError):
    """Another ingestion for the same source holds the advisory lock."""


class LoadFailedError(RuntimeError):
    """The atomic load failed; the run was marked failed and nothing was kept."""

    def __init__(self, run_id: uuid.UUID, cause: BaseException) -> None:
        super().__init__(f"ingestion run {run_id} failed: {cause}")
        self.run_id = run_id
        self.cause = cause


# ============================================================ pass 1


@dataclass(frozen=True, slots=True)
class KeyInfo:
    """Security-level facts for one stock file."""

    source_key: str
    relative_path: str
    newest_name: str | None
    newest_date: date | None
    ticker_mismatch_values: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class PreparedSnapshot:
    """Result of pass 1: identity, inventory, and per-security facts."""

    root: Path
    source: SnapshotSource
    manifest: SnapshotManifest
    entries: tuple[InventoryEntry, ...]
    content_sha256: str
    snapshot_id: str
    keys: tuple[KeyInfo, ...]

    @property
    def stock_entries(self) -> tuple[InventoryEntry, ...]:
        return tuple(e for e in self.entries if e.role is FileRole.STOCK)

    def role_counts(self) -> dict[str, int]:
        counts = Counter(e.role.value for e in self.entries)
        return {role.value: counts.get(role.value, 0) for role in FileRole}


def prepare_snapshot(
    source: SnapshotSource, root: Path, *, expect_stock_files: int | None = None
) -> PreparedSnapshot:
    """Pass 1: inventory, hashes, stock inspection, identity. No database."""
    manifest = source.read_manifest(root)
    if manifest.source_id != source.source_id:
        raise StructuralError(f"manifest is for {manifest.source_id!r}, not {source.source_id!r}")
    entries: list[InventoryEntry] = []
    keys: list[KeyInfo] = []
    for rel in list_snapshot_files(root):
        role = source.classify(rel)
        data = read_bytes(root / rel)
        digest = sha256_hex(data)
        info = source.inspect(rel, data, role)
        entries.append(
            InventoryEntry(rel, digest, len(data), role, info.row_count, info.source_key)
        )
        if role is FileRole.STOCK:
            if info.source_key is None:
                raise StructuralError(f"stock file without a source key: {rel}")
            keys.append(
                KeyInfo(
                    info.source_key,
                    rel,
                    info.newest_name,
                    info.newest_date,
                    info.ticker_mismatch_values,
                )
            )
    stock_count = len(keys)
    if stock_count == 0:
        raise StructuralError(f"no stock files found under {root}")
    if expect_stock_files is not None and stock_count != expect_stock_files:
        raise StructuralError(f"expected {expect_stock_files} stock files, found {stock_count}")
    key_counts = Counter(k.source_key for k in keys)
    if duplicated := sorted(k for k, n in key_counts.items() if n > 1):
        raise StructuralError(f"source keys appear in more than one file: {duplicated}")
    content = content_sha256(entries)
    return PreparedSnapshot(
        root=root,
        source=source,
        manifest=manifest,
        entries=tuple(entries),
        content_sha256=content,
        snapshot_id=derive_snapshot_id(source.source_id, manifest.revision, content),
        keys=tuple(sorted(keys, key=lambda k: k.source_key)),
    )


# ============================================================ incidents


@dataclass(frozen=True, slots=True)
class IncidentDraft:
    """An incident prepared in Python; `fingerprint` makes insertion idempotent."""

    incident_type: str
    severity: str
    source_key: str | None
    trading_date: date | None
    relative_path: str | None
    source_line: int | None
    details: dict[str, Any]

    @property
    def fingerprint(self) -> str:
        payload = {
            "type": self.incident_type,
            "key": self.source_key,
            "date": self.trading_date.isoformat() if self.trading_date else None,
            "path": self.relative_path,
            "line": self.source_line,
            "details": self.details,
        }
        encoded = json.dumps(payload, sort_keys=True, default=str).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()


# ============================================================ pass 2


@dataclass(frozen=True, slots=True)
class AcceptedRow:
    line: int
    price: DailyPrice


@dataclass(frozen=True, slots=True)
class FileOutcome:
    """Pass-2 result for one stock file (the only file held in memory)."""

    entry: InventoryEntry
    source_key: str
    rows_seen: int
    accepted: tuple[AcceptedRow, ...]
    rows_rejected: int
    rows_collapsed: int
    batch_rejected: bool
    incidents: tuple[IncidentDraft, ...]


def _observation(price: DailyPrice) -> tuple[object, ...]:
    return tuple(getattr(price, f.name) for f in fields(price) if f.name != "provenance")


def process_file(prepared: PreparedSnapshot, entry: InventoryEntry, data: bytes) -> FileOutcome:
    """Validate, quarantine, and de-duplicate one stock file's rows."""
    key = entry.source_key
    if key is None:
        raise StructuralError(f"stock file without a source key: {entry.relative_path}")
    results = list(
        prepared.source.iter_rows(entry.relative_path, data, entry.sha256, prepared.manifest)
    )
    incidents: list[IncidentDraft] = []
    rejected = 0
    candidates: dict[date, list[AcceptedRow]] = defaultdict(list)
    for result in sorted(results, key=lambda r: r.line):
        reasons = result.reasons
        if result.price is not None:
            if result.price.price_basis is not PriceBasis.RAW:
                raise StructuralError(f"{entry.relative_path}: loader accepts raw prices only")
            hard = [
                i.code
                for i in validate_daily_price(result.price)
                if i.severity is Severity.HARD_INVALID
            ]
            if not hard:
                candidates[result.price.trade_date].append(AcceptedRow(result.line, result.price))
                continue
            reasons = tuple(hard)
        rejected += 1
        incidents.append(
            IncidentDraft(
                "hard_invalid_record",
                "error",
                key,
                result.price.trade_date if result.price else None,
                entry.relative_path,
                result.line,
                {"reasons": list(reasons), "cells": list(result.cells)},
            )
        )
    accepted: list[AcceptedRow] = []
    collapsed = 0
    conflicts: dict[str, list[int]] = {}
    for trade_date, rows in sorted(candidates.items()):
        if len({_observation(r.price) for r in rows}) > 1:
            conflicts[trade_date.isoformat()] = sorted(r.line for r in rows)
            continue
        ordered = sorted(rows, key=lambda r: r.line)
        accepted.append(ordered[0])
        collapsed += len(ordered) - 1
    if conflicts:
        incidents.append(
            IncidentDraft(
                "conflicting_duplicate_in_snapshot",
                "error",
                key,
                None,
                entry.relative_path,
                None,
                {"conflicting_lines_by_date": conflicts},
            )
        )
        return FileOutcome(entry, key, len(results), (), len(results), 0, True, tuple(incidents))
    return FileOutcome(
        entry,
        key,
        len(results),
        tuple(sorted(accepted, key=lambda r: r.price.trade_date)),
        rejected,
        collapsed,
        False,
        tuple(incidents),
    )


def iter_file_outcomes(prepared: PreparedSnapshot) -> Iterator[FileOutcome]:
    """Pass 2, lazily: one stock file read, verified, and processed at a time."""
    for entry in prepared.stock_entries:
        data = read_bytes(prepared.root / entry.relative_path)
        if sha256_hex(data) != entry.sha256:
            raise StructuralError(f"{entry.relative_path} changed since it was inventoried")
        yield process_file(prepared, entry, data)


# ============================================================ counters & reports


@dataclass
class Counters:
    """Run counters; `rows_*` obey the invariant checked by `consistent`."""

    rows_seen: int = 0
    rows_inserted: int = 0
    rows_unchanged: int = 0
    rows_rejected: int = 0
    rows_conflicted: int = 0
    rows_collapsed_duplicates: int = 0
    incidents_created: int = 0
    files_processed: int = 0
    files_failed: int = 0
    securities_created: int = 0
    securities_resolved: int = 0

    def consistent(self) -> bool:
        return self.rows_seen == (
            self.rows_inserted
            + self.rows_unchanged
            + self.rows_rejected
            + self.rows_conflicted
            + self.rows_collapsed_duplicates
        )


@dataclass
class ObservationStats:
    """Summary of accepted observations (deterministic)."""

    statuses: Counter[str] = field(default_factory=Counter)
    flags: Counter[str] = field(default_factory=Counter)
    missing_open: int = 0
    zero_volume: int = 0
    first_date: date | None = None
    last_date: date | None = None

    def add(self, price: DailyPrice) -> None:
        self.statuses[price.trading_status.value] += 1
        self.flags.update(price.quality_flags)
        self.missing_open += price.open is None
        self.zero_volume += price.volume_shares == 0
        d = price.trade_date
        self.first_date = d if self.first_date is None else min(self.first_date, d)
        self.last_date = d if self.last_date is None else max(self.last_date, d)

    def as_dict(self) -> dict[str, Any]:
        return {
            "status_counts": {s.value: self.statuses.get(s.value, 0) for s in TradingStatus},
            "flag_counts": dict(sorted(self.flags.items())),
            "missing_open": self.missing_open,
            "zero_volume": self.zero_volume,
            "date_range": [
                self.first_date.isoformat() if self.first_date else None,
                self.last_date.isoformat() if self.last_date else None,
            ],
        }


def key_incidents(prepared: PreparedSnapshot) -> list[IncidentDraft]:
    """Security-level incidents implied by pass 1 (ticker-column mismatches)."""
    return [
        IncidentDraft(
            FLAG_TICKER_COLUMN_MISMATCH,
            "warning",
            k.source_key,
            None,
            k.relative_path,
            None,
            {"source_key": k.source_key, "raw_ticker_values": list(k.ticker_mismatch_values)},
        )
        for k in prepared.keys
        if k.ticker_mismatch_values
    ]


def _identity(prepared: PreparedSnapshot) -> dict[str, Any]:
    m = prepared.manifest
    return {
        "source_id": prepared.source.source_id,
        "source_revision": m.revision,
        "snapshot_id": prepared.snapshot_id,
        "content_sha256": prepared.content_sha256,
        "archive_sha256": m.archive_sha256,
        "archive_verified": False,
        "retrieved_at": m.retrieved_at.astimezone(UTC).isoformat(),
        "parser_version": prepared.source.parser_version,
        "files_by_role": prepared.role_counts(),
    }


def dry_run(prepared: PreparedSnapshot) -> dict[str, Any]:
    """Pass 2 with zero database access; report as for a load into an empty DB."""
    counters = Counters(
        securities_created=len(prepared.keys), securities_resolved=len(prepared.keys)
    )
    stats = ObservationStats()
    incidents = key_incidents(prepared)
    rejected_keys: list[str] = []
    for outcome in iter_file_outcomes(prepared):
        counters.files_processed += 1
        counters.rows_seen += outcome.rows_seen
        counters.rows_rejected += outcome.rows_rejected
        counters.rows_collapsed_duplicates += outcome.rows_collapsed
        counters.rows_inserted += len(outcome.accepted)
        if outcome.batch_rejected:
            counters.files_failed += 1
            rejected_keys.append(outcome.source_key)
        incidents.extend(outcome.incidents)
        for row in outcome.accepted:
            stats.add(row.price)
    counters.incidents_created = len({i.fingerprint for i in incidents})
    return {
        "mode": "dry_run",
        "identity": _identity(prepared),
        "counters": asdict(counters),
        "counters_consistent": counters.consistent(),
        "observations": stats.as_dict(),
        "rejected_security_batches": sorted(rejected_keys),
        "incidents": sorted(
            (
                {
                    "type": i.incident_type,
                    "severity": i.severity,
                    "source_key": i.source_key,
                    "relative_path": i.relative_path,
                    "source_line": i.source_line,
                    "fingerprint": i.fingerprint,
                }
                for i in incidents
            ),
            key=lambda d: str(d["fingerprint"]),
        ),
        "stock_files": [
            {
                "relative_path": e.relative_path,
                "sha256": e.sha256,
                "row_count": e.row_count,
                "source_key": e.source_key,
            }
            for e in prepared.stock_entries
        ],
    }


def report_json(report: dict[str, Any]) -> str:
    """Canonical JSON for reports (stable key order, no wall-clock values)."""
    return json.dumps(report, sort_keys=True, indent=2, default=str)


# ============================================================ database load


@dataclass(frozen=True, slots=True)
class LoadResult:
    run_id: uuid.UUID
    snapshot_id: str
    counters: Counters
    validation_summary: dict[str, Any]


def advisory_lock_key(source_id: str) -> int:
    digest = hashlib.sha256(f"stock-ai:ingest:{source_id}".encode()).digest()
    return int.from_bytes(digest[:8], "big", signed=True)


_OBS_D = ", ".join(f"d.{c}" for c in OBSERVATION_COLUMNS)
_OBS_S = ", ".join(f"s.{c}" for c in OBSERVATION_COLUMNS)
_KEY_JOIN = (
    "d.security_id = s.security_id AND d.trading_date = s.trading_date AND d.source_id = :source_id"
)


def _json_obj(prefix: str) -> str:
    return (
        "jsonb_build_object(" + ", ".join(f"'{c}', {prefix}.{c}" for c in OBSERVATION_COLUMNS) + ")"
    )


def try_source_lock(conn: Connection, source_id: str) -> bool:
    """Take the per-source session advisory lock; False if another session holds it."""
    got = conn.execute(
        text("SELECT pg_try_advisory_lock(:k)"), {"k": advisory_lock_key(source_id)}
    ).scalar_one()
    conn.commit()
    return bool(got)


def release_source_lock(conn: Connection, source_id: str) -> None:
    conn.execute(text("SELECT pg_advisory_unlock(:k)"), {"k": advisory_lock_key(source_id)})
    conn.commit()


def register_snapshot(
    conn: Connection,
    *,
    source_id: str,
    source_name: str,
    homepage_url: str | None,
    parser_version: str,
    manifest: SnapshotManifest,
    entries: Sequence[InventoryEntry],
    content_sha256: str,
    snapshot_id: str,
    root: Path,
) -> tuple[uuid.UUID, dict[str, int], list[str]]:
    """T0 for any source: data source, snapshot, file inventory, and a new run.

    Returns the run id, ``relative_path -> file_id``, and the ids of other
    snapshots with the same revision but different content (for a
    ``snapshot_content_mismatch`` incident).
    """
    conn.execute(
        pg_insert(DataSource)
        .values(source_id=source_id, source_name=source_name, homepage_url=homepage_url)
        .on_conflict_do_nothing(index_elements=["source_id"])
    )
    existing = conn.execute(
        select(SourceSnapshot.snapshot_id).where(
            SourceSnapshot.source_id == source_id,
            SourceSnapshot.source_revision == manifest.revision,
            SourceSnapshot.content_sha256 == content_sha256,
        )
    ).scalar_one_or_none()
    mismatch_with: list[str] = []
    if existing is None:
        mismatch_with = sorted(
            conn.execute(
                select(SourceSnapshot.snapshot_id).where(
                    SourceSnapshot.source_id == source_id,
                    SourceSnapshot.source_revision == manifest.revision,
                )
            ).scalars()
        )
        conn.execute(
            pg_insert(SourceSnapshot).values(
                snapshot_id=snapshot_id,
                source_id=source_id,
                source_revision=manifest.revision,
                content_sha256=content_sha256,
                archive_sha256=manifest.archive_sha256,
                source_url=manifest.source_url,
                retrieved_at=manifest.retrieved_at,
                licence_reference=manifest.licence_reference,
                raw_storage_path=_storage_path(root),
                file_count=len(entries),
            )
        )
    conn.execute(
        pg_insert(SourceFile)
        .values(
            [
                {
                    "snapshot_id": snapshot_id,
                    "relative_path": e.relative_path,
                    "sha256": e.sha256,
                    "row_count": e.row_count,
                    "source_key": e.source_key,
                }
                for e in entries
            ]
        )
        .on_conflict_do_nothing(index_elements=["snapshot_id", "relative_path"])
    )
    stored = {
        path: (file_id, digest)
        for path, file_id, digest in conn.execute(
            select(SourceFile.relative_path, SourceFile.file_id, SourceFile.sha256).where(
                SourceFile.snapshot_id == snapshot_id
            )
        )
    }
    for e in entries:
        if stored.get(e.relative_path, (None, None))[1] != e.sha256:
            raise StructuralError(f"registered file differs: {e.relative_path}")
    if len(stored) != len(entries):
        raise StructuralError("registered file inventory differs from the snapshot")
    run_id = uuid.uuid4()
    conn.execute(
        pg_insert(IngestionRun).values(
            ingestion_run_id=run_id,
            snapshot_id=snapshot_id,
            parser_version=parser_version,
            started_at=datetime.now(UTC),
            status="running",
        )
    )
    return run_id, {path: v[0] for path, v in stored.items()}, mismatch_with


def snapshot_mismatch_incident(
    revision: str, content_hash: str, other_snapshots: list[str]
) -> IncidentDraft:
    return IncidentDraft(
        "snapshot_content_mismatch",
        "error",
        None,
        None,
        None,
        None,
        {
            "source_revision": revision,
            "content_sha256": content_hash,
            "other_snapshots_same_revision": other_snapshots,
        },
    )


def insert_incident_drafts(
    conn: Connection,
    source_id: str,
    run_id: uuid.UUID,
    drafts: Sequence[IncidentDraft],
    *,
    security_ids: dict[str, int],
    file_ids: dict[str, int],
) -> int:
    """Insert drafts whose fingerprint is not already recorded for this source."""
    if not drafts:
        return 0
    known = set(
        conn.execute(
            text(
                "SELECT details->>'fingerprint' FROM data_quality_incidents "
                "WHERE source_id = :s AND details->>'fingerprint' IS NOT NULL"
            ),
            {"s": source_id},
        ).scalars()
    )
    rows: list[dict[str, Any]] = []
    for draft in sorted(drafts, key=lambda d: d.fingerprint):
        fp = draft.fingerprint
        if fp in known:
            continue
        known.add(fp)
        rows.append(
            {
                "ingestion_run_id": run_id,
                "incident_type": draft.incident_type,
                "severity": draft.severity,
                "source_id": source_id,
                "security_id": security_ids.get(draft.source_key) if draft.source_key else None,
                "trading_date": draft.trading_date,
                "file_id": file_ids.get(draft.relative_path) if draft.relative_path else None,
                "source_line": draft.source_line,
                "details": {**draft.details, "fingerprint": fp},
            }
        )
    if rows:
        conn.execute(pg_insert(DataQualityIncident).values(rows))
    return len(rows)


def finish_run(
    conn: Connection, run_id: uuid.UUID, counters: Counters, summary: dict[str, Any]
) -> None:
    """Mark a run succeeded; `summary` also receives the full counter set."""
    summary["counters"] = asdict(counters)
    conn.execute(
        update(IngestionRun)
        .where(IngestionRun.ingestion_run_id == run_id)
        .values(
            status="succeeded",
            completed_at=datetime.now(UTC),
            rows_seen=counters.rows_seen,
            rows_inserted=counters.rows_inserted,
            rows_unchanged=counters.rows_unchanged,
            rows_rejected=counters.rows_rejected,
            rows_conflicted=counters.rows_conflicted,
            validation_summary=summary,
        )
    )


def mark_run_failed(conn: Connection, run_id: uuid.UUID, exc: BaseException) -> None:
    conn.execute(
        update(IngestionRun)
        .where(IngestionRun.ingestion_run_id == run_id)
        .values(
            status="failed",
            completed_at=datetime.now(UTC),
            validation_summary={"error": f"{type(exc).__name__}: {exc}", "phase": "load"},
        )
    )


class SnapshotLoader:
    """Loads a prepared snapshot into PostgreSQL (see module docstring)."""

    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    # -------------------------------------------------------------- public

    def load(self, prepared: PreparedSnapshot, *, confirm_revision: str) -> LoadResult:
        """Load `prepared`; `confirm_revision` must equal its manifest revision."""
        if confirm_revision != prepared.manifest.revision:
            raise LoadNotConfirmedError(
                f"confirm_revision {confirm_revision!r} does not match snapshot revision "
                f"{prepared.manifest.revision!r}; nothing was written"
            )
        source_id = prepared.source.source_id
        with self.engine.connect() as conn:
            if not try_source_lock(conn, source_id):
                raise LoaderBusyError(f"another ingestion for {source_id!r} is running")
            try:
                with conn.begin():
                    run_id, file_ids, t0_incidents = self._register(conn, prepared)
                try:
                    with conn.begin():
                        result = self._load_prices(conn, prepared, run_id, file_ids)
                        result.counters.incidents_created += t0_incidents
                        self._finish(conn, run_id, result)
                except Exception as exc:  # T1 already rolled back by the context manager
                    with conn.begin():
                        self._mark_failed(conn, run_id, exc)
                    raise LoadFailedError(run_id, exc) from exc
                return result
            finally:
                release_source_lock(conn, source_id)

    # -------------------------------------------------------------- T0

    def _register(
        self, conn: Connection, prepared: PreparedSnapshot
    ) -> tuple[uuid.UUID, dict[str, int], int]:
        src = prepared.source
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
        created = 0
        if mismatch_with:
            created = self._insert_incidents(
                conn,
                prepared,
                run_id,
                [
                    snapshot_mismatch_incident(
                        prepared.manifest.revision, prepared.content_sha256, mismatch_with
                    )
                ],
                security_ids={},
                file_ids={},
            )
        return run_id, file_ids, created

    # -------------------------------------------------------------- T1

    def _load_prices(
        self,
        conn: Connection,
        prepared: PreparedSnapshot,
        run_id: uuid.UUID,
        file_ids: dict[str, int],
    ) -> LoadResult:
        source_id = prepared.source.source_id
        counters = Counters()
        security_ids = self._resolve_securities(conn, prepared, counters)
        drafts = key_incidents(prepared)
        self._flag_source_keys(conn, prepared)

        conn.execute(
            text(
                f"CREATE TEMP TABLE {STAGE_TABLE} ("
                "security_id bigint NOT NULL, trading_date date NOT NULL, "
                "open numeric(20,4), high numeric(20,4), low numeric(20,4), "
                "close numeric(20,4) NOT NULL, reference_price numeric(20,4), "
                "volume bigint, value numeric(24,4), frequency bigint, "
                "trading_status text NOT NULL, quality_flags text[] NOT NULL, "
                "file_id bigint NOT NULL, source_line integer NOT NULL"
                ") ON COMMIT DROP"
            )
        )
        stats = ObservationStats()
        rejected_keys: list[str] = []
        self._stage(conn, prepared, security_ids, file_ids, counters, stats, drafts, rejected_keys)

        conn.execute(text(f"CREATE INDEX ON {STAGE_TABLE} (security_id, trading_date)"))
        conn.execute(text(f"ANALYZE {STAGE_TABLE}"))
        duplicated = conn.execute(
            text(
                f"SELECT count(*) FROM (SELECT 1 FROM {STAGE_TABLE} "
                "GROUP BY security_id, trading_date HAVING count(*) > 1) x"
            )
        ).scalar_one()
        if duplicated:
            raise StructuralError(f"{duplicated} duplicate keys reached staging")

        new, unchanged, conflicted = self._classify(conn, source_id)
        counters.rows_unchanged = unchanged
        counters.rows_conflicted = conflicted
        counters.incidents_created += self._insert_conflict_incidents(conn, source_id, run_id)
        inserted = self._insert_new(conn, source_id, run_id)
        if inserted != new:
            raise RuntimeError(f"inserted {inserted} rows but classified {new} as new")
        counters.rows_inserted = inserted
        counters.incidents_created += self._insert_incidents(
            conn, prepared, run_id, drafts, security_ids=security_ids, file_ids=file_ids
        )
        if not counters.consistent():
            raise RuntimeError(f"row counters are inconsistent: {asdict(counters)}")
        summary = {
            "mode": "load",
            "identity": _identity(prepared),
            "counters": asdict(counters),
            "observations_accepted": stats.as_dict(),
            "rejected_security_batches": sorted(rejected_keys),
        }
        return LoadResult(run_id, prepared.snapshot_id, counters, summary)

    def _resolve_securities(
        self, conn: Connection, prepared: PreparedSnapshot, counters: Counters
    ) -> dict[str, int]:
        source_id = prepared.source.source_id
        mapping = {
            key: sid
            for key, sid in conn.execute(
                select(SecuritySourceKey.source_key, SecuritySourceKey.security_id).where(
                    SecuritySourceKey.source_id == source_id
                )
            )
        }
        new_keys = [k for k in prepared.keys if k.source_key not in mapping]  # sorted order
        if new_keys:
            created = conn.execute(
                pg_insert(Security)
                .values(
                    [
                        {
                            "ticker": k.source_key,
                            "name": k.newest_name,
                            "identity_kind": "development",
                        }
                        for k in new_keys
                    ]
                )
                .returning(Security.security_id, Security.ticker),
                # RETURNING order follows VALUES order; map by ticker (= unique new key).
            ).all()
            by_ticker = {ticker: sid for sid, ticker in created}
            conn.execute(
                pg_insert(SecuritySourceKey).values(
                    [
                        {
                            "source_id": source_id,
                            "source_key": k.source_key,
                            "security_id": by_ticker[k.source_key],
                            "first_seen_snapshot_id": prepared.snapshot_id,
                        }
                        for k in new_keys
                    ]
                )
            )
            mapping.update({k.source_key: by_ticker[k.source_key] for k in new_keys})
        new_key_set = {k.source_key for k in new_keys}
        existing = [k for k in prepared.keys if k.source_key not in new_key_set]
        if existing:
            latest: dict[int, date] = {
                int(sid): max_date
                for sid, max_date in conn.execute(
                    text(
                        "SELECT security_id, max(trading_date) FROM daily_prices "
                        "WHERE source_id = :s AND security_id = ANY(:ids) GROUP BY security_id"
                    ),
                    {"s": source_id, "ids": [mapping[k.source_key] for k in existing]},
                )
            }
            for k in existing:
                sid = mapping[k.source_key]
                stored = latest.get(sid)
                if k.newest_date is not None and (stored is None or k.newest_date > stored):
                    conn.execute(
                        update(Security)
                        .where(Security.security_id == sid)
                        .values(name=k.newest_name, ticker=k.source_key)
                    )
        counters.securities_created = len(new_keys)
        counters.securities_resolved = len(prepared.keys)
        return mapping

    def _flag_source_keys(self, conn: Connection, prepared: PreparedSnapshot) -> None:
        flagged = [k.source_key for k in prepared.keys if k.ticker_mismatch_values]
        if not flagged:
            return
        conn.execute(
            text(
                "UPDATE security_source_keys SET quality_flags = ARRAY("
                "SELECT DISTINCT f FROM unnest(quality_flags || ARRAY[:flag]::text[]) f ORDER BY f)"
                " WHERE source_id = :s AND source_key = ANY(:keys)"
                " AND NOT (:flag = ANY(quality_flags))"
            ),
            {"flag": FLAG_TICKER_COLUMN_MISMATCH, "s": prepared.source.source_id, "keys": flagged},
        )

    def _stage(
        self,
        conn: Connection,
        prepared: PreparedSnapshot,
        security_ids: dict[str, int],
        file_ids: dict[str, int],
        counters: Counters,
        stats: ObservationStats,
        drafts: list[IncidentDraft],
        rejected_keys: list[str],
    ) -> None:
        """Stream accepted rows into staging with COPY, one file at a time."""
        raw = conn.connection.driver_connection
        if raw is None:
            raise RuntimeError("no psycopg connection available for COPY")
        with (
            raw.cursor() as cursor,
            cursor.copy(f"COPY {STAGE_TABLE} ({', '.join(STAGE_COLUMNS)}) FROM STDIN") as copy,
        ):
            copy.set_types(list(STAGE_TYPES))
            for outcome in iter_file_outcomes(prepared):
                counters.files_processed += 1
                counters.rows_seen += outcome.rows_seen
                counters.rows_rejected += outcome.rows_rejected
                counters.rows_collapsed_duplicates += outcome.rows_collapsed
                drafts.extend(outcome.incidents)
                if outcome.batch_rejected:
                    counters.files_failed += 1
                    rejected_keys.append(outcome.source_key)
                    continue
                sid = security_ids[outcome.source_key]
                fid = file_ids[outcome.entry.relative_path]
                for row in outcome.accepted:
                    p = row.price
                    stats.add(p)
                    copy.write_row(
                        (
                            sid,
                            p.trade_date,
                            p.open,
                            p.high,
                            p.low,
                            p.close,
                            p.reference_price,
                            p.volume_shares,
                            p.value,
                            p.frequency,
                            p.trading_status.value,
                            sorted(set(p.quality_flags)),
                            fid,
                            row.line,
                        )
                    )

    def _classify(self, conn: Connection, source_id: str) -> tuple[int, int, int]:
        row = conn.execute(
            text(
                "SELECT count(*) FILTER (WHERE d.security_id IS NULL), "
                f"count(*) FILTER (WHERE d.security_id IS NOT NULL AND ({_OBS_D}) "
                f"IS NOT DISTINCT FROM ({_OBS_S})), "
                f"count(*) FILTER (WHERE d.security_id IS NOT NULL AND ({_OBS_D}) "
                f"IS DISTINCT FROM ({_OBS_S})) "
                f"FROM {STAGE_TABLE} s LEFT JOIN daily_prices d ON {_KEY_JOIN}"
            ),
            {"source_id": source_id},
        ).one()
        return int(row[0]), int(row[1]), int(row[2])

    def _insert_conflict_incidents(
        self, conn: Connection, source_id: str, run_id: uuid.UUID
    ) -> int:
        fingerprint = (
            "encode(sha256(convert_to(concat_ws('|', 'conflicting_observation', :source_id, "
            f"s.security_id::text, s.trading_date::text, ROW({_OBS_S})::text), 'UTF8')), 'hex')"
        )
        result = conn.execute(
            text(
                "WITH c AS ("
                "SELECT s.security_id, s.trading_date, s.file_id, s.source_line, "
                f"{fingerprint} AS fp, "
                f"{_json_obj('d')} AS stored, {_json_obj('s')} AS incoming, "
                "jsonb_build_object('file_id', d.file_id, 'source_line', d.source_line, "
                "'ingestion_run_id', d.ingestion_run_id) AS stored_provenance "
                f"FROM {STAGE_TABLE} s JOIN daily_prices d ON {_KEY_JOIN} "
                f"WHERE ({_OBS_D}) IS DISTINCT FROM ({_OBS_S})) "
                "INSERT INTO data_quality_incidents (ingestion_run_id, incident_type, severity, "
                "source_id, security_id, trading_date, file_id, source_line, details) "
                "SELECT :run_id, 'conflicting_observation', 'error', :source_id, c.security_id, "
                "c.trading_date, c.file_id, c.source_line, jsonb_build_object("
                "'fingerprint', c.fp, 'stored', c.stored, 'incoming', c.incoming, "
                "'stored_provenance', c.stored_provenance, 'incoming_provenance', "
                "jsonb_build_object('file_id', c.file_id, 'source_line', c.source_line)) "
                "FROM c WHERE NOT EXISTS (SELECT 1 FROM data_quality_incidents i "
                "WHERE i.incident_type = 'conflicting_observation' "
                "AND i.details->>'fingerprint' = c.fp) "
                "ORDER BY c.security_id, c.trading_date"
            ),
            {"source_id": source_id, "run_id": run_id},
        )
        return int(result.rowcount)

    def _insert_new(self, conn: Connection, source_id: str, run_id: uuid.UUID) -> int:
        cols = ", ".join(STAGE_COLUMNS)
        result = conn.execute(
            text(
                f"INSERT INTO daily_prices ({cols}, source_id, ingestion_run_id) "
                f"SELECT {', '.join('s.' + c for c in STAGE_COLUMNS)}, :source_id, :run_id "
                f"FROM {STAGE_TABLE} s WHERE NOT EXISTS "
                f"(SELECT 1 FROM daily_prices d WHERE {_KEY_JOIN}) "
                "ORDER BY s.security_id, s.trading_date "
                "ON CONFLICT (security_id, trading_date, source_id) DO NOTHING"
            ),
            {"source_id": source_id, "run_id": run_id},
        )
        return int(result.rowcount)

    def _insert_incidents(
        self,
        conn: Connection,
        prepared: PreparedSnapshot,
        run_id: uuid.UUID,
        drafts: Sequence[IncidentDraft],
        *,
        security_ids: dict[str, int],
        file_ids: dict[str, int],
    ) -> int:
        return insert_incident_drafts(
            conn,
            prepared.source.source_id,
            run_id,
            drafts,
            security_ids=security_ids,
            file_ids=file_ids,
        )

    # -------------------------------------------------------------- run status

    def _finish(self, conn: Connection, run_id: uuid.UUID, result: LoadResult) -> None:
        finish_run(conn, run_id, result.counters, result.validation_summary)

    def _mark_failed(self, conn: Connection, run_id: uuid.UUID, exc: BaseException) -> None:
        mark_run_failed(conn, run_id, exc)


def _storage_path(root: Path) -> str:
    """Snapshot path relative to the project root when possible (never machine-specific)."""
    from backend.config import PROJECT_ROOT

    resolved = root.resolve()
    try:
        return resolved.relative_to(PROJECT_ROOT).as_posix()
    except ValueError:
        return resolved.as_posix()


__all__ = [
    "AcceptedRow",
    "Counters",
    "FileInspection",
    "FileOutcome",
    "IncidentDraft",
    "KeyInfo",
    "LoadFailedError",
    "LoadNotConfirmedError",
    "LoadResult",
    "LoaderBusyError",
    "PreparedSnapshot",
    "RowResult",
    "SnapshotLoader",
    "SnapshotSource",
    "advisory_lock_key",
    "dry_run",
    "finish_run",
    "insert_incident_drafts",
    "iter_file_outcomes",
    "key_incidents",
    "mark_run_failed",
    "prepare_snapshot",
    "process_file",
    "register_snapshot",
    "release_source_lock",
    "report_json",
    "snapshot_mismatch_incident",
    "try_source_lock",
]
