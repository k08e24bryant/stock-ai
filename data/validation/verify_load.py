"""Read-only post-load verification of a snapshot in PostgreSQL.

Purpose
    Implement the "verification after ingestion" checks of
    docs/data_sources/phase_2b_ingestion_design.md §13: does the database
    hold this snapshot exactly as the loader would have produced it, and do
    the database-level invariants hold?

Inputs
    * A `SnapshotSource` adapter and a snapshot directory. The **expected**
      values are computed from the snapshot itself with the loader's own
      pass 1 and pass 2 (no database access). No count is hard-coded.
    * An engine. The database is read inside one ``REPEATABLE READ, READ
      ONLY`` transaction that is always rolled back, so this module cannot
      write, and the session enforces that.

Outputs
    A `VerificationReport`: one `Check` (name, expected, actual, ok) per
    rule, printable as a table or as deterministic JSON. The CLI exits 0 when
    every check passes, 1 on any mismatch, and 2 on invalid input.

Assumptions
    * Source-level counts (rows, statuses, flags, keys) assume the source's
      canonical rows come from this one snapshot. This is true for the
      current development database. With several snapshots of one source,
      those counts legitimately differ; the per-row ``--deep`` comparison
      and the integrity checks still apply.
    * No conflicts are expected. Stored rows that differ from the snapshot
      show up in ``--deep`` as mismatches.

Limitations
    ``--deep`` issues one indexed query per security (983 for Pholenk) and
    re-reads every stock file; expect minutes on the full snapshot.

Example
    Verify the development load (read-only)::

        python -m data.validation.verify_load pholenk data/raw/pholenk/IDX-Dataset-9bb3b26 \\
            --expect-stock-files 983 --deep
"""

from __future__ import annotations

import argparse
import sys
from collections import Counter
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from sqlalchemy import Connection, Engine, Row, text

from backend.models.market_data import (
    ROW_QUALITY_FLAGS,
    SOURCE_KEY_QUALITY_FLAGS,
    TRADING_STATUSES,
)
from data.ingestion.loader import (
    FLAG_TICKER_COLUMN_MISMATCH,
    OBSERVATION_COLUMNS,
    ObservationStats,
    PreparedSnapshot,
    iter_file_outcomes,
    key_incidents,
    prepare_snapshot,
    report_json,
)
from data.ingestion.snapshot import StructuralError

# ============================================================ report model


@dataclass(frozen=True, slots=True)
class Check:
    """One verification rule: `ok` iff `actual == expected`."""

    group: str
    name: str
    expected: Any
    actual: Any

    @property
    def ok(self) -> bool:
        return bool(self.expected == self.actual)


@dataclass
class VerificationReport:
    snapshot_id: str
    deep: bool
    checks: list[Check] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return all(c.ok for c in self.checks)

    @property
    def failures(self) -> list[Check]:
        return [c for c in self.checks if not c.ok]

    def add(self, group: str, name: str, expected: Any, actual: Any) -> None:
        self.checks.append(Check(group, name, expected, actual))

    def as_dict(self) -> dict[str, Any]:
        """Deterministic (no wall-clock values)."""
        return {
            "mode": "verify_load",
            "snapshot_id": self.snapshot_id,
            "deep": self.deep,
            "ok": self.ok,
            "checks_total": len(self.checks),
            "checks_failed": len(self.failures),
            "checks": [
                {
                    "group": c.group,
                    "name": c.name,
                    "expected": c.expected,
                    "actual": c.actual,
                    "ok": c.ok,
                }
                for c in self.checks
            ],
        }

    def as_lines(self) -> list[str]:
        lines = [f"verify_load {self.snapshot_id} (deep={self.deep})"]
        for c in self.checks:
            status = "PASS" if c.ok else "FAIL"
            lines.append(
                f"{status}  {c.group}.{c.name}: expected {c.expected!r}, actual {c.actual!r}"
            )
        lines.append(
            f"{'OK' if self.ok else 'FAILED'}: "
            f"{len(self.checks) - len(self.failures)}/{len(self.checks)} checks passed"
        )
        return lines


# ============================================================ expectations (no database)


@dataclass
class _Expected:
    stats: ObservationStats = field(default_factory=ObservationStats)
    rows: int = 0
    rows_seen: int = 0
    multi_flag_rows: int = 0
    rows_by_path: dict[str, int] = field(default_factory=dict)
    incident_fingerprints: set[str] = field(default_factory=set)


# ============================================================ database checks

# Integrity rules: each query counts violations and must return 0. Rules that
# concern observations are scoped to the verified source (:src).
_INTEGRITY: tuple[tuple[str, str], ...] = (
    (
        "duplicate_price_key",
        "SELECT count(*) FROM (SELECT 1 FROM daily_prices WHERE source_id = :src "
        "GROUP BY security_id, trading_date, source_id HAVING count(*) > 1) x",
    ),
    (
        "ohlc_relationship",
        "SELECT count(*) FROM daily_prices WHERE source_id = :src AND ("
        "high < low OR high < close OR low > close "
        "OR (open IS NOT NULL AND (open > high OR open < low)))",
    ),
    (
        "non_positive_price",
        "SELECT count(*) FROM daily_prices WHERE source_id = :src AND ("
        "close <= 0 OR open <= 0 OR high <= 0 OR low <= 0 OR reference_price <= 0)",
    ),
    (
        "negative_volume_value_frequency",
        "SELECT count(*) FROM daily_prices WHERE source_id = :src AND ("
        "volume < 0 OR value < 0 OR frequency < 0)",
    ),
    (
        "invalid_trading_status",
        "SELECT count(*) FROM daily_prices WHERE source_id = :src "
        "AND NOT (trading_status = ANY(:statuses))",
    ),
    (
        "status_inconsistent_with_volume",
        "SELECT count(*) FROM daily_prices WHERE source_id = :src AND ("
        "(trading_status = 'traded' AND (volume IS NULL OR volume <= 0 "
        "OR high IS NULL OR low IS NULL)) "
        "OR (trading_status = 'no_regular_market_trade' AND (volume IS NULL OR volume <> 0)))",
    ),
    (
        "zero_volume_with_open_high_low",
        "SELECT count(*) FROM daily_prices WHERE source_id = :src AND volume = 0 "
        "AND (open IS NOT NULL OR high IS NOT NULL OR low IS NOT NULL)",
    ),
    (
        "invalid_row_flags",
        "SELECT count(*) FROM daily_prices WHERE source_id = :src AND ("
        "NOT (quality_flags <@ CAST(:row_flags AS text[])) "
        "OR array_position(quality_flags, NULL) IS NOT NULL)",
    ),
    (
        "unsorted_or_duplicate_row_flags",
        "SELECT count(*) FROM daily_prices WHERE source_id = :src AND quality_flags <> "
        "ARRAY(SELECT u.f FROM (SELECT DISTINCT f FROM unnest(quality_flags) f) u "
        'ORDER BY u.f COLLATE "C")',
    ),
    (
        "invalid_key_flags",
        "SELECT count(*) FROM security_source_keys WHERE source_id = :src "
        "AND NOT (quality_flags <@ CAST(:key_flags AS text[]))",
    ),
    (
        "price_from_unregistered_or_non_stock_file",
        "SELECT count(*) FROM daily_prices p LEFT JOIN source_files f USING (file_id) "
        "WHERE p.source_id = :src AND (f.file_id IS NULL OR f.source_key IS NULL)",
    ),
    (
        "price_file_key_differs_from_security_key",
        "SELECT count(*) FROM daily_prices p JOIN source_files f USING (file_id) "
        "JOIN security_source_keys k "
        "ON k.security_id = p.security_id AND k.source_id = p.source_id "
        "WHERE p.source_id = :src AND k.source_key <> f.source_key",
    ),
    (
        "price_without_source_key",
        "SELECT count(*) FROM daily_prices p LEFT JOIN security_source_keys k "
        "ON k.security_id = p.security_id AND k.source_id = p.source_id "
        "WHERE p.source_id = :src AND k.security_id IS NULL",
    ),
    (
        "source_line_outside_file",
        "SELECT count(*) FROM daily_prices p JOIN source_files f USING (file_id) "
        "WHERE p.source_id = :src AND (p.source_line < 2 OR p.source_line > f.row_count + 1)",
    ),
    (
        "duplicate_source_line",
        "SELECT count(*) FROM (SELECT 1 FROM daily_prices WHERE source_id = :src "
        "GROUP BY file_id, source_line HAVING count(*) > 1) x",
    ),
    (
        "price_from_unsuccessful_run",
        "SELECT count(*) FROM daily_prices p JOIN ingestion_runs r USING (ingestion_run_id) "
        "WHERE p.source_id = :src AND r.status <> 'succeeded'",
    ),
    (
        "file_snapshot_of_other_source",
        "SELECT count(*) FROM daily_prices p JOIN source_files f USING (file_id) "
        "JOIN source_snapshots s USING (snapshot_id) "
        "WHERE p.source_id = :src AND s.source_id <> p.source_id",
    ),
    (
        "security_not_development_identity",
        "SELECT count(*) FROM securities s JOIN security_source_keys k USING (security_id) "
        "WHERE k.source_id = :src AND s.identity_kind <> 'development'",
    ),
    (
        "security_ticker_differs_from_key",
        "SELECT count(*) FROM securities s JOIN security_source_keys k USING (security_id) "
        "WHERE k.source_id = :src AND s.ticker <> k.source_key",
    ),
    (
        "stale_running_run",
        "SELECT count(*) FROM ingestion_runs r JOIN source_snapshots s USING (snapshot_id) "
        "WHERE s.source_id = :src AND r.status = 'running'",
    ),
    (
        "run_counter_invariant",
        "SELECT count(*) FROM ingestion_runs r JOIN source_snapshots s USING (snapshot_id) "
        "WHERE s.source_id = :src AND r.status = 'succeeded' AND r.rows_seen <> "
        "r.rows_inserted + r.rows_unchanged + r.rows_rejected + r.rows_conflicted + "
        "coalesce((r.validation_summary->'counters'->>'rows_collapsed_duplicates')::bigint, 0)",
    ),
    (
        "adjustment_columns_present",
        "SELECT count(*) FROM information_schema.columns WHERE table_name = 'daily_prices' "
        "AND (column_name ILIKE '%adj%' OR column_name ILIKE '%factor%' "
        "OR column_name ILIKE '%split%')",
    ),
)

_PRICE_AGGREGATES = (
    "SELECT count(*) AS rows, "
    "count(*) FILTER (WHERE open IS NULL) AS missing_open, "
    "count(*) FILTER (WHERE volume = 0) AS zero_volume, "
    "count(*) FILTER (WHERE cardinality(quality_flags) >= 2) AS multi_flag_rows, "
    "min(trading_date) AS first_date, max(trading_date) AS last_date "
    "FROM daily_prices WHERE source_id = :src"
)


def _pairs(rows: Iterable[Row[Any]]) -> dict[Any, Any]:
    """Two-column result rows as a dict (first column -> second column)."""
    return {r[0]: r[1] for r in rows}


def _begin_read_only(conn: Connection) -> None:
    conn.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY"))


def _scalar(conn: Connection, sql: str, **params: Any) -> Any:
    return conn.execute(text(sql), params).scalar_one()


def _check_registration(
    conn: Connection, prepared: PreparedSnapshot, report: VerificationReport
) -> bool:
    snap = (
        conn.execute(
            text(
                "SELECT source_id, source_revision, content_sha256, file_count "
                "FROM source_snapshots WHERE snapshot_id = :sid"
            ),
            {"sid": prepared.snapshot_id},
        )
        .mappings()
        .one_or_none()
    )
    report.add("snapshot", "registered", True, snap is not None)
    if snap is None:
        return False
    report.add("snapshot", "source_id", prepared.source.source_id, snap["source_id"])
    report.add("snapshot", "source_revision", prepared.manifest.revision, snap["source_revision"])
    report.add("snapshot", "content_sha256", prepared.content_sha256, snap["content_sha256"])
    report.add("snapshot", "file_count", len(prepared.entries), snap["file_count"])
    stored = {
        (path, digest, rows, key)
        for path, digest, rows, key in conn.execute(
            text(
                "SELECT relative_path, sha256, row_count, source_key FROM source_files "
                "WHERE snapshot_id = :sid"
            ),
            {"sid": prepared.snapshot_id},
        )
    }
    expected = {(e.relative_path, e.sha256, e.row_count, e.source_key) for e in prepared.entries}
    report.add("files", "registered", len(expected), len(stored))
    report.add("files", "differing_from_disk", 0, len(expected ^ stored))
    succeeded = _scalar(
        conn,
        "SELECT count(*) FROM ingestion_runs WHERE snapshot_id = :sid AND status = 'succeeded'",
        sid=prepared.snapshot_id,
    )
    report.add("run", "has_succeeded_run", True, succeeded > 0)
    return True


def _check_keys(conn: Connection, prepared: PreparedSnapshot, report: VerificationReport) -> None:
    src = prepared.source.source_id
    stored = _pairs(
        conn.execute(
            text(
                "SELECT source_key, quality_flags FROM security_source_keys WHERE source_id = :src"
            ),
            {"src": src},
        ).all()
    )
    expected_keys = {k.source_key for k in prepared.keys}
    report.add("securities", "source_keys", len(expected_keys), len(stored))
    report.add("securities", "keys_differing_from_snapshot", 0, len(expected_keys ^ set(stored)))
    expected_flagged = sorted(k.source_key for k in prepared.keys if k.ticker_mismatch_values)
    flagged = sorted(k for k, flags in stored.items() if FLAG_TICKER_COLUMN_MISMATCH in flags)
    report.add("securities", "ticker_column_mismatch_keys", expected_flagged, flagged)


def _check_prices(
    conn: Connection, prepared: PreparedSnapshot, exp: _Expected, report: VerificationReport
) -> None:
    src = prepared.source.source_id
    agg = conn.execute(text(_PRICE_AGGREGATES), {"src": src}).mappings().one()
    obs = exp.stats.as_dict()
    first, last = obs["date_range"]
    report.add("prices", "rows", exp.rows, agg["rows"])
    report.add("prices", "missing_open", obs["missing_open"], agg["missing_open"])
    report.add("prices", "zero_volume", obs["zero_volume"], agg["zero_volume"])
    report.add("prices", "rows_with_multiple_flags", exp.multi_flag_rows, agg["multi_flag_rows"])
    report.add(
        "prices",
        "date_range",
        [first, last],
        [
            agg["first_date"].isoformat() if agg["first_date"] else None,
            agg["last_date"].isoformat() if agg["last_date"] else None,
        ],
    )
    statuses = _pairs(
        conn.execute(
            text(
                "SELECT trading_status, count(*) FROM daily_prices WHERE source_id = :src "
                "GROUP BY trading_status"
            ),
            {"src": src},
        ).all()
    )
    for status, expected in obs["status_counts"].items():
        report.add("prices", f"status.{status}", expected, statuses.get(status, 0))
    flag_counts = _pairs(
        conn.execute(
            text(
                "SELECT f, count(*) FROM daily_prices, unnest(quality_flags) f "
                "WHERE source_id = :src GROUP BY f"
            ),
            {"src": src},
        ).all()
    )
    for flag in sorted(set(ROW_QUALITY_FLAGS) | set(obs["flag_counts"])):
        report.add(
            "prices", f"flag.{flag}", obs["flag_counts"].get(flag, 0), flag_counts.get(flag, 0)
        )
    per_file = _pairs(
        conn.execute(
            text(
                "SELECT f.relative_path, count(p.file_id) FROM source_files f "
                "LEFT JOIN daily_prices p ON p.file_id = f.file_id "
                "WHERE f.snapshot_id = :sid AND f.source_key IS NOT NULL GROUP BY f.relative_path"
            ),
            {"sid": prepared.snapshot_id},
        ).all()
    )
    differing = sum(1 for path, n in exp.rows_by_path.items() if per_file.get(path, 0) != n) + len(
        set(per_file) - set(exp.rows_by_path)
    )
    report.add("prices", "stock_files_with_row_count_mismatch", 0, differing)


def _check_incidents(
    conn: Connection, prepared: PreparedSnapshot, exp: _Expected, report: VerificationReport
) -> None:
    stored = set(
        conn.execute(
            text(
                "SELECT details->>'fingerprint' FROM data_quality_incidents "
                "WHERE source_id = :src AND details ? 'fingerprint'"
            ),
            {"src": prepared.source.source_id},
        ).scalars()
    )
    report.add(
        "incidents",
        "expected",
        len(exp.incident_fingerprints),
        len(exp.incident_fingerprints & stored),
    )


def _check_latest_run(
    conn: Connection, prepared: PreparedSnapshot, exp: _Expected, report: VerificationReport
) -> None:
    seen = conn.execute(
        text(
            "SELECT rows_seen FROM ingestion_runs WHERE snapshot_id = :sid "
            "AND status = 'succeeded' ORDER BY completed_at DESC LIMIT 1"
        ),
        {"sid": prepared.snapshot_id},
    ).scalar_one_or_none()
    report.add("run", "latest_succeeded_rows_seen", exp.rows_seen, seen)


def _check_integrity(conn: Connection, source_id: str, report: VerificationReport) -> None:
    params = {
        "src": source_id,
        "statuses": list(TRADING_STATUSES),
        "row_flags": list(ROW_QUALITY_FLAGS),
        "key_flags": list(SOURCE_KEY_QUALITY_FLAGS),
    }
    for name, sql in _INTEGRITY:
        used = {k: v for k, v in params.items() if f":{k}" in sql}
        report.add("integrity", name, 0, int(conn.execute(text(sql), used).scalar_one()))


def _collect_and_compare(
    conn: Connection,
    prepared: PreparedSnapshot,
    report: VerificationReport,
    *,
    deep: bool,
) -> _Expected:
    """One pass over the snapshot: expectations, and (deep) per-row comparison."""
    exp = _Expected()
    exp.incident_fingerprints.update(i.fingerprint for i in key_incidents(prepared))
    src = prepared.source.source_id
    key_to_security: dict[str, int] = {}
    path_to_file: dict[str, int] = {}
    if deep:
        key_to_security = _pairs(
            conn.execute(
                text(
                    "SELECT source_key, security_id FROM security_source_keys "
                    "WHERE source_id = :src"
                ),
                {"src": src},
            ).all()
        )
        path_to_file = _pairs(
            conn.execute(
                text("SELECT relative_path, file_id FROM source_files WHERE snapshot_id = :sid"),
                {"sid": prepared.snapshot_id},
            ).all()
        )
    diff: Counter[str] = Counter()
    columns = ", ".join(OBSERVATION_COLUMNS)
    for outcome in iter_file_outcomes(prepared):
        exp.incident_fingerprints.update(i.fingerprint for i in outcome.incidents)
        exp.rows_by_path[outcome.entry.relative_path] = len(outcome.accepted)
        exp.rows_seen += outcome.rows_seen
        for row in outcome.accepted:
            exp.rows += 1
            exp.stats.add(row.price)
            exp.multi_flag_rows += len(set(row.price.quality_flags)) >= 2
        if not deep:
            continue
        security_id = key_to_security.get(outcome.source_key)
        stored = (
            {
                r[0]: r[1:]
                for r in conn.execute(
                    text(
                        f"SELECT trading_date, {columns}, file_id, source_line FROM daily_prices "
                        "WHERE security_id = :sid AND source_id = :src"
                    ),
                    {"sid": security_id, "src": src},
                )
            }
            if security_id is not None
            else {}
        )
        file_id = path_to_file.get(outcome.entry.relative_path)
        for row in outcome.accepted:
            p = row.price
            incoming = (
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
            )
            got = stored.pop(p.trade_date, None)
            if got is None:
                diff["missing"] += 1
            elif tuple(got[:-2]) != incoming:  # Decimal compares by value
                diff["observation_differs"] += 1
            elif tuple(got[-2:]) != (file_id, row.line):
                diff["provenance_differs"] += 1
        diff["extra"] += len(stored)
    if deep:
        for kind in ("missing", "observation_differs", "provenance_differs", "extra"):
            report.add("rows", kind, 0, diff[kind])
    return exp


# ============================================================ public API


def verify(engine: Engine, prepared: PreparedSnapshot, *, deep: bool = False) -> VerificationReport:
    """Verify `prepared` against the database, read-only; never writes."""
    report = VerificationReport(prepared.snapshot_id, deep)
    with engine.connect() as conn:
        try:
            _begin_read_only(conn)
            report.add(
                "session",
                "read_only",
                "on",
                _scalar(conn, "SHOW transaction_read_only"),
            )
            registered = _check_registration(conn, prepared, report)
            exp = _collect_and_compare(conn, prepared, report, deep=deep and registered)
            _check_latest_run(conn, prepared, exp, report)
            _check_keys(conn, prepared, report)
            _check_prices(conn, prepared, exp, report)
            _check_incidents(conn, prepared, exp, report)
            _check_integrity(conn, prepared.source.source_id, report)
        finally:
            conn.rollback()
    return report


def main(argv: Sequence[str] | None = None) -> int:
    from data.ingestion.load_snapshot import SOURCES

    parser = argparse.ArgumentParser(
        description="Read-only verification of a loaded snapshot (ingestion design §13)."
    )
    parser.add_argument("source", choices=sorted(SOURCES))
    parser.add_argument("root", type=Path, help="snapshot directory containing manifest.json")
    parser.add_argument(
        "--expect-stock-files",
        type=int,
        default=None,
        metavar="N",
        help="fail unless exactly N stock files are found (Pholenk: 983)",
    )
    parser.add_argument(
        "--deep",
        action="store_true",
        help="also compare every stored row with the snapshot (slower)",
    )
    parser.add_argument("--report", type=Path, default=None, help="write the JSON report here")
    args = parser.parse_args(argv)

    try:
        prepared = prepare_snapshot(
            SOURCES[args.source](), args.root, expect_stock_files=args.expect_stock_files
        )
    except StructuralError as exc:
        print(f"structural error: {exc}", file=sys.stderr)
        return 2

    from backend.database import get_engine

    report = verify(get_engine(), prepared, deep=args.deep)
    print("\n".join(report.as_lines()))
    if args.report is not None:
        args.report.write_text(report_json(report.as_dict()) + "\n", encoding="utf-8")
    return 0 if report.ok else 1


if __name__ == "__main__":
    sys.exit(main())


__all__ = ["Check", "VerificationReport", "main", "verify"]
