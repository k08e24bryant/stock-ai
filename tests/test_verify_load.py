"""Tests for the read-only post-load verification (`data.validation.verify_load`).

All database tests run against a throwaway database (``migrated_database``),
never the development database. Fixture snapshots are the small synthetic
ones from the loader tests.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from sqlalchemy import Engine, text
from test_ingestion_loader import (
    OTHER_REVISION,
    TABLES,
    build_snapshot,
    load,
    prepared_for,
    row,
    standard_stocks,
)

from data.validation import verify_load
from data.validation.verify_load import VerificationReport, verify

pytestmark = pytest.mark.integration


@pytest.fixture
def engine(migrated_database: Engine) -> Engine:
    with migrated_database.begin() as conn:
        conn.execute(text(f"TRUNCATE {TABLES} RESTART IDENTITY"))
    return migrated_database


def failed(report: VerificationReport) -> dict[str, tuple[object, object]]:
    return {f"{c.group}.{c.name}": (c.expected, c.actual) for c in report.failures}


def table_counts(engine: Engine) -> dict[str, int]:
    with engine.connect() as conn:
        return {
            t.strip(): int(conn.execute(text(f"SELECT count(*) FROM {t}")).scalar_one())
            for t in TABLES.split(",")
        }


@pytest.mark.parametrize("deep", [False, True], ids=["summary", "deep"])
def test_a_clean_load_verifies(tmp_path: Path, engine: Engine, deep: bool) -> None:
    root = build_snapshot(tmp_path / "s", standard_stocks())
    load(engine, root)
    before = table_counts(engine)
    report = verify(engine, prepared_for(root), deep=deep)
    assert report.ok, failed(report)
    checks = {f"{c.group}.{c.name}": c.actual for c in report.checks}
    assert checks["session.read_only"] == "on"  # the database enforced read-only
    assert checks["prices.rows"] == 6
    assert checks["prices.rows_with_multiple_flags"] == 1
    assert checks["securities.ticker_column_mismatch_keys"] == ["TRUE"]
    assert ("rows.missing" in checks) is deep
    assert table_counts(engine) == before  # nothing written


def test_an_unloaded_snapshot_fails_without_crashing(tmp_path: Path, engine: Engine) -> None:
    report = verify(engine, prepared_for(build_snapshot(tmp_path / "s", standard_stocks())))
    assert not report.ok
    assert failed(report)["snapshot.registered"] == (True, False)
    assert failed(report)["prices.rows"] == (6, 0)


def test_a_changed_stored_value_is_found_by_the_deep_check(tmp_path: Path, engine: Engine) -> None:
    root = build_snapshot(tmp_path / "s", standard_stocks())
    load(engine, root)
    with engine.begin() as conn:  # simulate out-of-band tampering in the test database
        conn.execute(
            text(
                "UPDATE daily_prices SET close = close + 25, high = high + 25 "
                "WHERE trading_date = '2026-05-29' AND security_id = "
                "(SELECT security_id FROM security_source_keys WHERE source_key = 'TLKM')"
            )
        )
    assert verify(engine, prepared_for(root)).ok  # the summary counts cannot see it
    deep = verify(engine, prepared_for(root), deep=True)
    assert failed(deep) == {"rows.observation_differs": (0, 1)}


def test_a_missing_row_fails_counts_and_deep(tmp_path: Path, engine: Engine) -> None:
    root = build_snapshot(tmp_path / "s", standard_stocks())
    load(engine, root)
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM daily_prices WHERE trading_date = '2021-05-22'"))
    report = verify(engine, prepared_for(root), deep=True)
    problems = failed(report)
    assert problems["prices.rows"] == (6, 5)
    assert problems["prices.flag.unverified_trading_date"] == (1, 0)
    assert problems["prices.stock_files_with_row_count_mismatch"] == (0, 1)
    assert problems["rows.missing"] == (0, 1)


def test_a_stale_running_run_is_reported(tmp_path: Path, engine: Engine) -> None:
    root = build_snapshot(tmp_path / "s", standard_stocks())
    result = load(engine, root)
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO ingestion_runs (ingestion_run_id, snapshot_id, parser_version, "
                "started_at, status) VALUES (gen_random_uuid(), :sid, 'x', now(), 'running')"
            ),
            {"sid": result.snapshot_id},
        )
    assert failed(verify(engine, prepared_for(root))) == {"integrity.stale_running_run": (0, 1)}


def test_after_a_conflicting_snapshot_the_first_one_still_verifies(
    tmp_path: Path, engine: Engine
) -> None:
    root_v1 = build_snapshot(tmp_path / "v1", standard_stocks())
    load(engine, root_v1)
    changed = standard_stocks()
    changed["TLKM"] = [row(Date="2026-05-29", Ticker="TLKM", Close="5725.0")]
    root_v2 = build_snapshot(tmp_path / "v2", changed, revision=OTHER_REVISION)
    load(engine, root_v2, revision=OTHER_REVISION)
    # Nothing was overwritten: the database still holds v1 exactly.
    v1 = verify(engine, prepared_for(root_v1), deep=True)
    assert v1.ok, failed(v1)
    # v2 did not load these rows (documented single-snapshot assumption): the
    # conflicting observation differs, and the 5 unchanged rows keep v1's
    # provenance, so v2's 3 stock files own none of the rows.
    assert failed(verify(engine, prepared_for(root_v2), deep=True)) == {
        "rows.observation_differs": (0, 1),
        "rows.provenance_differs": (0, 5),
        "prices.stock_files_with_row_count_mismatch": (0, 3),
    }


def test_cli_exit_codes_and_deterministic_report(
    tmp_path: Path, engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = build_snapshot(tmp_path / "s", standard_stocks())
    load(engine, root)
    monkeypatch.setattr("backend.database.get_engine", lambda: engine)
    first, second = tmp_path / "r1.json", tmp_path / "r2.json"
    args = ["pholenk", str(root), "--deep"]
    assert verify_load.main([*args, "--report", str(first)]) == 0
    assert verify_load.main([*args, "--report", str(second)]) == 0
    assert first.read_bytes() == second.read_bytes()
    assert json.loads(first.read_text(encoding="utf-8"))["ok"] is True
    assert verify_load.main(["pholenk", str(root), "--expect-stock-files", "983"]) == 2
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM daily_prices WHERE trading_date = '2021-05-22'"))
    assert verify_load.main(args) == 1
