"""Phase 2B.3B loader tests on small synthetic snapshots.

Pure tests (identity, inventory, dry run, streaming, CLI safety) need no
database. Database tests (marked ``integration``) run against a **throwaway
database** migrated to ``head`` (the ``migrated_database`` fixture in
``conftest.py``) and dropped afterwards, so the development database is never
touched; tables are truncated between tests.

Letters in section headers refer to the Phase 2B.3B test plan (A-J).
"""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import Engine, func, select, text
from sqlalchemy.orm import Session

import data.ingestion.loader as loader_module
import data.ingestion.snapshot as snapshot_module
from backend.models import (
    DailyPrice,
    DataQualityIncident,
    IngestionRun,
    Security,
    SecuritySourceKey,
    SourceFile,
    SourceSnapshot,
)
from data.ingestion import load_snapshot
from data.ingestion.loader import (
    LoaderBusyError,
    LoadFailedError,
    LoadNotConfirmedError,
    LoadResult,
    PreparedSnapshot,
    SnapshotLoader,
    advisory_lock_key,
    dry_run,
    iter_file_outcomes,
    prepare_snapshot,
    report_json,
)
from data.ingestion.pholenk import EXPECTED_COLUMNS, SOURCE_ID
from data.ingestion.pholenk_snapshot import PholenkSnapshotSource
from data.ingestion.snapshot import FileRole, StructuralError

REVISION = "9bb3b26bd28ab46bc2f3e74a7c03805ce053301b"
OTHER_REVISION = "0" * 40
SOURCE = PholenkSnapshotSource()

Rows = list[dict[str, str]]

# --------------------------------------------------------------------------
# Fixture snapshots
# --------------------------------------------------------------------------


def row(**overrides: str) -> dict[str, str]:
    """A valid traded Pholenk row; override any column by name."""
    base = dict.fromkeys(EXPECTED_COLUMNS, "0")
    base.update(
        Date="2026-05-29",
        Ticker="BBCA",
        Name="Bank Central Asia Tbk.",
        Remarks="--U-2130",
        Previous="5975.0",
        Open="5750.0",
        High="5875.0",
        Low="5700.0",
        Close="5700.0",
        Change="-275.0",
        Volume="1015296600",
        Value="5822702632500",
        Frequency="111208",
    )
    base.update(overrides)
    return base


def no_trade(**overrides: str) -> dict[str, str]:
    """A zero-regular-volume row as the source publishes it (OHLC zero)."""
    base = row(
        Open="0.0", High="0.0", Low="0.0", Close="535.0", Previous="535.0",
        Change="0.0", Volume="0", Value="0", Frequency="0",
    )  # fmt: skip
    base.update(overrides)
    return base


def csv_bytes(rows: Rows) -> bytes:
    """UTF-8 with BOM and CRLF, like the real snapshot."""
    lines = [",".join(EXPECTED_COLUMNS)]
    lines += [",".join(r[c] for c in EXPECTED_COLUMNS) for r in rows]
    return b"\xef\xbb\xbf" + ("\r\n".join(lines) + "\r\n").encode("utf-8")


def build_snapshot(
    root: Path,
    stocks: dict[str, Rows],
    *,
    revision: str = REVISION,
    retrieved_at: str = "2026-09-24T11:28:14Z",
) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    manifest = {
        "source_id": SOURCE_ID,
        "source_url": "https://github.com/Pholenk/IDX-Dataset",
        "revision": revision,
        "archive_sha256": "5" * 64,
        "retrieved_at": retrieved_at,
        "licence": "ODbL-1.0 (test fixture)",
        "licence_read_on": "2026-09-24",
    }
    (root / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    stock_dir = root / "dataset" / "stocks" / "csv"
    stock_dir.mkdir(parents=True, exist_ok=True)
    for key, rows in stocks.items():
        (stock_dir / f"{key}.csv").write_bytes(csv_bytes(rows))
    index_dir = root / "dataset" / "indices" / "csv"
    index_dir.mkdir(parents=True, exist_ok=True)
    (index_dir / "COMPOSITE.csv").write_text("Date,Close\n2026-05-29,6127.381\n", encoding="utf-8")
    preview_dir = root / "dataset" / "preview" / "stocks" / "csv"
    preview_dir.mkdir(parents=True, exist_ok=True)
    (preview_dir / "AADI.csv").write_bytes(csv_bytes([row(Ticker="AADI")]))
    (root / "metadata.json").write_text('{"license": "ODbL"}', encoding="utf-8")
    (root / "Readme.md").write_text("# fixture\n", encoding="utf-8")
    return root


def standard_stocks() -> dict[str, Rows]:
    """3 securities, 6 rows; newest first, as in the source."""
    return {
        "BBCA": [
            row(Date="2026-05-29"),
            row(Date="2026-05-28", Open="0.0", NonRegularVolume="56560625"),
            no_trade(Date="2021-05-22", NonRegularVolume="400"),  # a Saturday
        ],
        "TLKM": [row(Date="2026-05-29", Ticker="TLKM", Name="Telkom Indonesia Tbk.")],
        "TRUE": [
            row(Date="2026-05-29", Ticker="True", Name="Triwira Insanlestari Tbk."),
            row(Date="2026-05-28", Ticker="True", Name="Triwira Insanlestari Tbk."),
        ],
    }


def prepared_for(root: Path, expect_stock_files: int | None = None) -> PreparedSnapshot:
    return prepare_snapshot(SOURCE, root, expect_stock_files=expect_stock_files)


# --------------------------------------------------------------------------
# A. Snapshot identity and inventory (no database)
# --------------------------------------------------------------------------


def test_same_content_same_identity_regardless_of_retrieval_time(tmp_path: Path) -> None:
    a = prepared_for(build_snapshot(tmp_path / "a", standard_stocks()))
    b = prepared_for(
        build_snapshot(tmp_path / "b", standard_stocks(), retrieved_at="2030-01-01T00:00:00Z")
    )
    assert a.content_sha256 == b.content_sha256
    assert a.snapshot_id == b.snapshot_id == f"{SOURCE_ID}:{REVISION}:{a.content_sha256[:16]}"


def test_changed_content_changes_identity(tmp_path: Path) -> None:
    a = prepared_for(build_snapshot(tmp_path / "a", standard_stocks()))
    changed = standard_stocks()
    changed["TLKM"] = [row(Date="2026-05-29", Ticker="TLKM", Close="5725.0")]
    b = prepared_for(build_snapshot(tmp_path / "b", changed))
    assert a.content_sha256 != b.content_sha256
    assert a.snapshot_id != b.snapshot_id


def test_only_stock_files_become_securities(tmp_path: Path) -> None:
    prepared = prepared_for(build_snapshot(tmp_path / "s", standard_stocks()))
    assert [k.source_key for k in prepared.keys] == ["BBCA", "TLKM", "TRUE"]
    assert prepared.role_counts() == {"stock": 3, "index": 1, "preview": 1, "other": 2}
    assert "manifest.json" not in {e.relative_path for e in prepared.entries}
    preview = next(e for e in prepared.entries if e.role is FileRole.PREVIEW)
    assert preview.source_key is None


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda d: (d / "bbca-old.csv").write_bytes(csv_bytes([row()])), "unexpected file"),
        (lambda d: (d / "notes.txt").write_text("x"), "unexpected file"),
        (lambda d: (d / "BBCA.csv").write_text("Date,Close\n2026-05-29,1\n"), "unexpected header"),
        (lambda d: (d / "BBCA.csv").write_bytes(b"\xef\xbb\xbfDate\xff\xfe"), "not valid UTF-8"),
    ],
    ids=["bad-stock-filename", "stray-file", "bad-header", "bad-encoding"],
)
def test_structural_problems_fail_before_any_write(
    tmp_path: Path, mutate: Callable[[Path], object], message: str
) -> None:
    root = build_snapshot(tmp_path / "s", standard_stocks())
    mutate(root / "dataset" / "stocks" / "csv")
    with pytest.raises(StructuralError, match=message):
        prepared_for(root)


def test_expected_stock_file_count_is_enforced(tmp_path: Path) -> None:
    root = build_snapshot(tmp_path / "s", standard_stocks())
    with pytest.raises(StructuralError, match="expected 983 stock files, found 3"):
        prepared_for(root, expect_stock_files=983)


# --------------------------------------------------------------------------
# B / J. Single-read hashing and streaming (no database)
# --------------------------------------------------------------------------


def test_each_file_is_read_once_and_hashed_from_those_bytes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = build_snapshot(tmp_path / "s", standard_stocks())
    reads: list[bytes] = []
    real = snapshot_module.read_bytes

    def spy(path: Path) -> bytes:
        data = real(path)
        reads.append(data)
        return data

    monkeypatch.setattr(loader_module, "read_bytes", spy)
    prepared = prepared_for(root)
    assert len(reads) == len(prepared.entries)  # exactly one read per file in pass 1
    assert {e.sha256 for e in prepared.entries} == {snapshot_module.sha256_hex(d) for d in reads}


def test_pass_two_is_lazy_one_file_at_a_time(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    prepared = prepared_for(build_snapshot(tmp_path / "s", standard_stocks()))
    reads: list[str] = []
    real = snapshot_module.read_bytes

    def spy(path: Path) -> bytes:
        reads.append(path.name)
        return real(path)

    monkeypatch.setattr(loader_module, "read_bytes", spy)
    outcomes = iter_file_outcomes(prepared)
    assert reads == []  # a generator: nothing is read until consumed
    first = next(outcomes)
    assert reads == ["BBCA.csv"] and first.source_key == "BBCA"
    next(outcomes)
    assert reads == ["BBCA.csv", "TLKM.csv"]  # only stock files, one at a time


def test_dry_run_is_deterministic_and_consistent(tmp_path: Path) -> None:
    prepared = prepared_for(build_snapshot(tmp_path / "s", standard_stocks()))
    first, second = report_json(dry_run(prepared)), report_json(dry_run(prepared))
    assert first == second
    report = json.loads(first)
    assert report["counters_consistent"] is True
    assert report["counters"]["rows_seen"] == 6
    assert report["counters"]["rows_inserted"] == 6
    assert report["observations"]["status_counts"] == {
        "traded": 5,
        "no_regular_market_trade": 1,
        "unknown": 0,
    }
    assert report["observations"]["flag_counts"] == {
        "non_regular_activity_present": 2,
        "unverified_trading_date": 1,
    }
    assert report["observations"]["missing_open"] == 2  # Open=0 row and the zero-volume row


def test_cli_defaults_to_dry_run_and_requires_confirmation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    root = build_snapshot(tmp_path / "s", standard_stocks())

    def forbidden() -> None:
        raise AssertionError("the database must not be touched")

    monkeypatch.setattr("backend.database.get_engine", forbidden)
    assert load_snapshot.main(["pholenk", str(root)]) == 0
    assert json.loads(capsys.readouterr().out)["mode"] == "dry_run"
    assert load_snapshot.main(["pholenk", str(root), "--execute"]) == 2
    short = ["--execute", "--confirm-revision", REVISION[:7]]
    assert load_snapshot.main(["pholenk", str(root), *short]) == 2
    assert load_snapshot.main(["pholenk", str(root), "--expect-stock-files", "983"]) == 2


# --------------------------------------------------------------------------
# Database fixtures (throwaway database)
# --------------------------------------------------------------------------

TABLES = (
    "daily_prices, data_quality_incidents, security_source_keys, securities, "
    "ingestion_runs, source_files, source_snapshots, data_sources"
)


@pytest.fixture
def engine(migrated_database: Engine) -> Engine:
    with migrated_database.begin() as conn:
        conn.execute(text(f"TRUNCATE {TABLES} RESTART IDENTITY"))
    return migrated_database


def load(engine: Engine, root: Path, revision: str = REVISION) -> LoadResult:
    return SnapshotLoader(engine).load(prepared_for(root), confirm_revision=revision)


def scalar(engine: Engine, statement: Any) -> Any:
    with Session(engine) as session:
        return session.scalars(statement).one()


def objects(engine: Engine, statement: Any) -> list[Any]:
    with Session(engine) as session:
        return list(session.scalars(statement))


def count(engine: Engine, model: Any) -> int:
    return int(scalar(engine, select(func.count()).select_from(model)))


def prices(engine: Engine) -> dict[tuple[str, date], DailyPrice]:
    with Session(engine) as session:
        rows = session.execute(
            select(DailyPrice, SecuritySourceKey.source_key).join(
                SecuritySourceKey, SecuritySourceKey.security_id == DailyPrice.security_id
            )
        ).all()
    return {(key, p.trading_date): p for p, key in rows}


def incidents_of(engine: Engine, incident_type: str) -> list[DataQualityIncident]:
    return objects(
        engine,
        select(DataQualityIncident).where(DataQualityIncident.incident_type == incident_type),
    )


# --------------------------------------------------------------------------
# Real-load safety
# --------------------------------------------------------------------------


@pytest.mark.integration
def test_load_requires_exact_revision_confirmation(tmp_path: Path, engine: Engine) -> None:
    prepared = prepared_for(build_snapshot(tmp_path / "s", standard_stocks()))
    with pytest.raises(LoadNotConfirmedError):
        SnapshotLoader(engine).load(prepared, confirm_revision=REVISION[:7])
    assert count(engine, SourceSnapshot) == 0
    assert count(engine, IngestionRun) == 0


@pytest.mark.integration
def test_concurrent_load_is_refused(tmp_path: Path, engine: Engine) -> None:
    prepared = prepared_for(build_snapshot(tmp_path / "s", standard_stocks()))
    lock = {"k": advisory_lock_key(SOURCE_ID)}
    with engine.connect() as other:
        other.execute(text("SELECT pg_advisory_lock(:k)"), lock)
        with pytest.raises(LoaderBusyError):
            SnapshotLoader(engine).load(prepared, confirm_revision=REVISION)
        other.execute(text("SELECT pg_advisory_unlock(:k)"), lock)
    assert count(engine, IngestionRun) == 0


# --------------------------------------------------------------------------
# C / D / E / H. First load: identity, normalization, flags, provenance
# --------------------------------------------------------------------------


@pytest.mark.integration
def test_first_load(tmp_path: Path, engine: Engine) -> None:
    result = load(engine, build_snapshot(tmp_path / "s", standard_stocks()))
    c = result.counters
    assert (c.rows_seen, c.rows_inserted, c.rows_unchanged, c.rows_conflicted) == (6, 6, 0, 0)
    assert (c.securities_created, c.securities_resolved, c.files_processed) == (3, 3, 3)
    assert c.incidents_created == 1 and c.consistent()

    # C. identity: the file key is the identity; TRUE stays TRUE; one security per key
    keys = {k.source_key: k for k in objects(engine, select(SecuritySourceKey))}
    assert {k: v.quality_flags for k, v in keys.items()} == {
        "BBCA": [],
        "TLKM": [],
        "TRUE": ["source_ticker_column_mismatch"],
    }
    securities = {s.security_id: s for s in objects(engine, select(Security))}
    assert len(securities) == 3 and len({k.security_id for k in keys.values()}) == 3
    true_security = securities[keys["TRUE"].security_id]
    assert (true_security.ticker, true_security.name) == ("TRUE", "Triwira Insanlestari Tbk.")
    assert {s.identity_kind for s in securities.values()} == {"development"}
    [mismatch] = incidents_of(engine, "source_ticker_column_mismatch")
    assert mismatch.details["raw_ticker_values"] == ["True"]
    assert mismatch.security_id == keys["TRUE"].security_id

    # run bookkeeping; files of every role inventoried, prices only from stock files
    run = scalar(engine, select(IngestionRun))
    assert (run.ingestion_run_id, run.status, run.parser_version) == (
        result.run_id,
        "succeeded",
        "pholenk-csv-2",
    )
    assert (run.rows_seen, run.rows_inserted) == (6, 6) and run.completed_at is not None
    assert run.validation_summary["counters"]["securities_created"] == 3
    files = {f.relative_path: f for f in objects(engine, select(SourceFile))}
    assert len(files) == 7 and files["dataset/stocks/csv/BBCA.csv"].row_count == 3
    snapshot = scalar(engine, select(SourceSnapshot))
    assert (snapshot.snapshot_id, snapshot.file_count) == (result.snapshot_id, 7)

    p = prices(engine)
    assert len(p) == 6 and {k for k, _ in p} == {"BBCA", "TLKM", "TRUE"}
    # D. normalization
    traded = p[("BBCA", date(2026, 5, 29))]
    assert (traded.open, traded.close, traded.reference_price, traded.volume) == (
        Decimal("5750"),
        Decimal("5700"),
        Decimal("5975"),
        1015296600,
    )
    assert traded.trading_status == "traded"
    assert p[("BBCA", date(2026, 5, 28))].open is None  # Open=0 -> NULL, never filled
    zero = p[("BBCA", date(2021, 5, 22))]
    assert (zero.open, zero.high, zero.low, zero.volume) == (None, None, None, 0)
    assert (zero.close, zero.reference_price) == (Decimal("535"), Decimal("535"))
    assert zero.trading_status == "no_regular_market_trade"
    # E. flags: documented vocabulary, sorted, deduplicated
    assert zero.quality_flags == ["non_regular_activity_present", "unverified_trading_date"]
    assert p[("BBCA", date(2026, 5, 28))].quality_flags == ["non_regular_activity_present"]
    assert traded.quality_flags == []
    # H. provenance
    assert traded.file_id == files["dataset/stocks/csv/BBCA.csv"].file_id
    assert (traded.source_line, zero.source_line) == (2, 4)
    assert {x.ingestion_run_id for x in p.values()} == {result.run_id}


# --------------------------------------------------------------------------
# G / H. Idempotency and conflicts
# --------------------------------------------------------------------------


@pytest.mark.integration
def test_identical_rerun_changes_nothing(tmp_path: Path, engine: Engine) -> None:
    root = build_snapshot(tmp_path / "s", standard_stocks())
    first = load(engine, root)
    before = {k: (v.file_id, v.source_line, v.ingestion_run_id) for k, v in prices(engine).items()}
    second = load(engine, root)
    c = second.counters
    assert (c.rows_inserted, c.rows_unchanged, c.rows_conflicted) == (0, 6, 0)
    assert (c.incidents_created, c.securities_created, c.securities_resolved) == (0, 0, 3)
    assert second.snapshot_id == first.snapshot_id and second.run_id != first.run_id
    after = {k: (v.file_id, v.source_line, v.ingestion_run_id) for k, v in prices(engine).items()}
    assert after == before  # provenance of unchanged rows is not rewritten
    assert count(engine, SourceSnapshot) == 1
    assert count(engine, SourceFile) == 7
    assert count(engine, DataQualityIncident) == 1
    assert count(engine, IngestionRun) == 2


@pytest.mark.integration
def test_conflicting_observation_is_recorded_not_overwritten(
    tmp_path: Path, engine: Engine
) -> None:
    load(engine, build_snapshot(tmp_path / "v1", standard_stocks()))
    changed = standard_stocks()
    changed["TLKM"] = [row(Date="2026-05-29", Ticker="TLKM", Name="Telkom", Close="5725.0")]
    root_v2 = build_snapshot(tmp_path / "v2", changed, revision=OTHER_REVISION)
    result = load(engine, root_v2, revision=OTHER_REVISION)
    c = result.counters
    assert (c.rows_inserted, c.rows_unchanged, c.rows_conflicted) == (0, 5, 1)
    assert c.incidents_created == 1 and c.consistent()
    stored = prices(engine)[("TLKM", date(2026, 5, 29))]
    assert stored.close == Decimal("5700")  # the stored observation is kept
    [conflict] = incidents_of(engine, "conflicting_observation")
    assert conflict.ingestion_run_id == result.run_id
    assert conflict.details["stored"]["close"] == 5700
    assert conflict.details["incoming"]["close"] == 5725
    assert conflict.details["stored_provenance"]["ingestion_run_id"] == str(stored.ingestion_run_id)
    assert conflict.details["incoming_provenance"]["file_id"] != stored.file_id
    # the same conflicting snapshot again: counted, but no duplicate incident
    again = load(engine, root_v2, revision=OTHER_REVISION)
    assert again.counters.rows_conflicted == 1 and again.counters.incidents_created == 0
    assert len(incidents_of(engine, "conflicting_observation")) == 1


@pytest.mark.integration
def test_name_updates_only_from_newer_observations(tmp_path: Path, engine: Engine) -> None:
    load(engine, build_snapshot(tmp_path / "v1", standard_stocks()))
    same_date = standard_stocks()
    same_date["TLKM"] = [row(Date="2026-05-29", Ticker="TLKM", Name="Old Name")]
    load(
        engine,
        build_snapshot(tmp_path / "v0", same_date, revision=OTHER_REVISION),
        revision=OTHER_REVISION,
    )
    name = select(Security.name).where(Security.ticker == "TLKM")
    assert scalar(engine, name) == "Telkom Indonesia Tbk."  # not replaced without newer data
    newer = standard_stocks()
    newer["TLKM"] = [row(Date="2026-06-01", Ticker="TLKM", Name="Telkom Baru Tbk.")]
    rev = "1" * 40
    load(engine, build_snapshot(tmp_path / "v3", newer, revision=rev), revision=rev)
    assert scalar(engine, name) == "Telkom Baru Tbk."
    assert count(engine, Security) == 3  # same key, same security


# --------------------------------------------------------------------------
# F. Validation and quarantine
# --------------------------------------------------------------------------


@pytest.mark.integration
def test_bad_rows_are_quarantined_and_the_file_continues(tmp_path: Path, engine: Engine) -> None:
    stocks = standard_stocks()
    stocks["TLKM"] = [
        row(Date="2026-05-29", Ticker="TLKM"),
        row(Date="2026-05-28", Ticker="TLKM", High="5600.0"),  # high < low: hard-invalid
        row(Date="2026-05-27", Ticker="TLKM", Close="n/a"),  # unparseable number
    ]
    c = load(engine, build_snapshot(tmp_path / "s", stocks)).counters
    assert (c.rows_seen, c.rows_inserted, c.rows_rejected) == (8, 6, 2) and c.consistent()
    assert [d for k, d in prices(engine) if k == "TLKM"] == [date(2026, 5, 29)]
    bad = incidents_of(engine, "hard_invalid_record")
    assert sorted(i.source_line or 0 for i in bad) == [3, 4]
    assert any("high_below_low" in i.details["reasons"] for i in bad)
    assert all(i.status == "open" and i.file_id is not None for i in bad)


@pytest.mark.integration
def test_conflicting_duplicate_rejects_the_security_batch(tmp_path: Path, engine: Engine) -> None:
    stocks = standard_stocks()
    stocks["TLKM"] = [
        row(Date="2026-05-29", Ticker="TLKM"),
        row(Date="2026-05-29", Ticker="TLKM", Close="5725.0"),
        row(Date="2026-05-28", Ticker="TLKM"),
    ]
    result = load(engine, build_snapshot(tmp_path / "s", stocks))
    c = result.counters
    assert (c.rows_seen, c.rows_rejected, c.files_failed, c.rows_inserted) == (8, 3, 1, 5)
    assert c.consistent()
    assert not any(k == "TLKM" for k, _ in prices(engine))
    assert result.validation_summary["rejected_security_batches"] == ["TLKM"]
    [dup] = incidents_of(engine, "conflicting_duplicate_in_snapshot")
    assert dup.details["conflicting_lines_by_date"] == {"2026-05-29": [2, 3]}


@pytest.mark.integration
def test_exact_duplicate_collapses(tmp_path: Path, engine: Engine) -> None:
    stocks = standard_stocks()
    stocks["TLKM"] = [row(Date="2026-05-29", Ticker="TLKM"), row(Date="2026-05-29", Ticker="TLKM")]
    c = load(engine, build_snapshot(tmp_path / "s", stocks)).counters
    assert (c.rows_seen, c.rows_inserted, c.rows_collapsed_duplicates) == (7, 6, 1)
    assert c.consistent()
    assert prices(engine)[("TLKM", date(2026, 5, 29))].source_line == 2  # lowest line kept


# --------------------------------------------------------------------------
# B / I. Failures leave nothing partial
# --------------------------------------------------------------------------


def _assert_nothing_loaded(engine: Engine) -> None:
    for model in (DailyPrice, Security, SecuritySourceKey, DataQualityIncident):
        assert count(engine, model) == 0, model.__name__
    run = scalar(engine, select(IngestionRun))
    assert run.status == "failed" and run.completed_at is not None
    assert "error" in run.validation_summary
    assert count(engine, SourceSnapshot) == 1  # registration evidence is kept (T0)


@pytest.mark.integration
def test_bytes_changed_after_hashing_fail_the_run(tmp_path: Path, engine: Engine) -> None:
    root = build_snapshot(tmp_path / "s", standard_stocks())
    prepared = prepared_for(root)
    (root / "dataset" / "stocks" / "csv" / "TLKM.csv").write_bytes(
        csv_bytes([row(Date="2026-05-29", Ticker="TLKM", Close="5800.0")])
    )
    with pytest.raises(LoadFailedError, match="changed since it was inventoried"):
        SnapshotLoader(engine).load(prepared, confirm_revision=REVISION)
    _assert_nothing_loaded(engine)


@pytest.mark.integration
def test_injected_failure_rolls_back_everything(
    tmp_path: Path, engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    def boom(*args: object, **kwargs: object) -> int:
        raise RuntimeError("injected failure after staging")

    root = build_snapshot(tmp_path / "s", standard_stocks())
    monkeypatch.setattr(SnapshotLoader, "_insert_new", boom)
    with pytest.raises(LoadFailedError, match="injected failure"):
        load(engine, root)
    _assert_nothing_loaded(engine)
    monkeypatch.undo()
    retry = load(engine, root)  # once the cause is gone, a retry is a clean first load
    assert retry.counters.rows_inserted == 6 and retry.counters.securities_created == 3


# --------------------------------------------------------------------------
# Advisory lock lifecycle and comparison semantics
# --------------------------------------------------------------------------

_ADVISORY_LOCKS = (
    "SELECT count(*) FROM pg_locks WHERE locktype = 'advisory' "
    "AND database = (SELECT oid FROM pg_database WHERE datname = current_database())"
)


def advisory_locks_held(engine: Engine) -> int:
    with engine.connect() as conn:
        return int(conn.execute(text(_ADVISORY_LOCKS)).scalar_one())


@pytest.mark.integration
def test_lock_is_held_during_writes_and_released_after_success_and_failure(
    tmp_path: Path, engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = build_snapshot(tmp_path / "s", standard_stocks())
    held_during_registration: list[int] = []
    real_register = SnapshotLoader._register

    def register(self: SnapshotLoader, conn: Any, prepared: PreparedSnapshot) -> Any:
        held_during_registration.append(
            int(
                conn.execute(
                    text(_ADVISORY_LOCKS + " AND pid = pg_backend_pid() AND granted")
                ).scalar_one()
            )
        )
        return real_register(self, conn, prepared)

    monkeypatch.setattr(SnapshotLoader, "_register", register)
    load(engine, root)
    assert held_during_registration == [1]  # the lock precedes the first write
    assert advisory_locks_held(engine) == 0  # released after success

    def boom(*args: object, **kwargs: object) -> int:
        raise RuntimeError("injected failure")

    monkeypatch.setattr(SnapshotLoader, "_insert_new", boom)
    with pytest.raises(LoadFailedError):
        load(engine, root)
    assert advisory_locks_held(engine) == 0  # released after failure


@pytest.mark.integration
def test_flag_only_difference_is_a_conflict(tmp_path: Path, engine: Engine) -> None:
    load(engine, build_snapshot(tmp_path / "v1", standard_stocks()))
    changed = standard_stocks()
    changed["TLKM"] = [row(Date="2026-05-29", Ticker="TLKM", NonRegularVolume="10")]
    c = load(
        engine, build_snapshot(tmp_path / "v2", changed, revision=OTHER_REVISION), OTHER_REVISION
    ).counters
    assert (c.rows_unchanged, c.rows_conflicted, c.rows_inserted) == (5, 1, 0)
    assert prices(engine)[("TLKM", date(2026, 5, 29))].quality_flags == []  # not overwritten


@pytest.mark.integration
def test_numeric_formatting_difference_is_unchanged(tmp_path: Path, engine: Engine) -> None:
    load(engine, build_snapshot(tmp_path / "v1", standard_stocks()))
    reformatted = standard_stocks()
    reformatted["TLKM"] = [
        row(
            Date="2026-05-29", Ticker="TLKM", Name="Telkom Indonesia Tbk.",
            Open="5750", High="5875.00", Low="5700", Close="5700.000", Previous="5975",
        )
    ]  # fmt: skip
    rev = "2" * 40
    result = load(engine, build_snapshot(tmp_path / "v2", reformatted, revision=rev), rev)
    c = result.counters
    assert (c.rows_unchanged, c.rows_conflicted, c.rows_inserted) == (6, 0, 0)
    assert c.incidents_created == 0  # numbers compare by value, not by text
