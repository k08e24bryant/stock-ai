"""Phase 2D: index files, index loader, observed trading calendar, benchmark series.

Database tests run in the throwaway ``migrated_database``. The fixture
snapshot reuses the loader tests' stock files and replaces their placeholder
``COMPOSITE.csv`` with real-format index files:

| Date | Stocks | COMPOSITE | Notes |
| --- | --- | --- | --- |
| 2021-05-21 (Fri) | yes | yes | |
| 2021-05-22 (Sat) | yes | yes | flagged ``unverified_trading_date`` |
| 2021-05-24 (Mon) | yes | yes | COMPOSITE ``previous`` ≠ prior close |
| 2021-05-25 (Tue) | no | yes | a day missing from the stock data |
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, insert, inspect, text
from sqlalchemy.exc import IntegrityError
from test_ingestion_loader import TABLES, build_snapshot, load, row

from backend.models import IndexDailyValue, metadata
from data.features.index_series import index_returns, load_index_series
from data.ingestion.loader import LoadNotConfirmedError, prepare_snapshot
from data.ingestion.pholenk_indices import HEADER, PholenkIndexSource, parse_index_file
from data.ingestion.pholenk_snapshot import PholenkSnapshotSource
from data.ingestion.records import RecordLoader, prepare_record_snapshot
from data.ingestion.snapshot import StructuralError
from data.validation.verify_load import verify, verify_records

REVISION = "9bb3b26bd28ab46bc2f3e74a7c03805ce053301b"
ALEMBIC_INI = Path(__file__).resolve().parents[1] / "alembic.ini"
COMPOSITE = "dataset/indices/csv/COMPOSITE.csv"


def index_csv(rows: list[tuple[str, str, str, str, str]]) -> bytes:
    """Rows of (date, previous, high, low, close); newest first like the source."""
    lines = [",".join(HEADER)]
    for day, prev, high, low, close in rows:
        change = str(Decimal(close) - Decimal(prev))
        lines.append(f"{day},{prev},{high},{low},{close},900,{change},1000,5000,10,70000")
    return b"\xef\xbb\xbf" + ("\r\n".join(lines) + "\r\n").encode()


COMPOSITE_ROWS = [
    ("2021-05-25", "5900", "5950", "5890", "5940"),
    ("2021-05-24", "5773.12", "5910", "5760", "5900"),  # previous != 5-22 close
    ("2021-05-22", "5840", "5930", "5835", "5920.844"),
    ("2021-05-21", "5800", "5850", "5790", "5840"),
]


def snapshot(root: Path) -> Path:
    stocks = {
        "BBCA": [row(Date=d) for d in ("2021-05-24", "2021-05-22", "2021-05-21")],
        "TLKM": [row(Date=d, Ticker="TLKM") for d in ("2021-05-24", "2021-05-21")],
    }
    build_snapshot(root, stocks)
    (root / COMPOSITE).write_bytes(index_csv(COMPOSITE_ROWS))
    (root / "dataset/indices/csv/LQ45.csv").write_bytes(
        index_csv([("2021-05-21", "900", "910", "890", "905")])
    )
    return root


# --------------------------------------------------------------------------
# Parser (no database)
# --------------------------------------------------------------------------


def test_parser_values_flags_and_line_numbers() -> None:
    records = parse_index_file(COMPOSITE, index_csv(COMPOSITE_ROWS))
    by_date = {r.values["trading_date"]: r for r in records if r.values}
    assert len(by_date) == 4 and [r.record_ref for r in records] == ["2", "3", "4", "5"]
    sat = by_date[date(2021, 5, 22)].values
    assert sat is not None and sat["quality_flags"] == ["unverified_trading_date"]
    assert sat["close"] == Decimal("5920.844") and sat["index_code"] == "COMPOSITE"
    assert by_date[date(2021, 5, 21)].values["quality_flags"] == []  # type: ignore[index]


def test_parser_rejects_inconsistent_rows_and_bad_structure() -> None:
    bad_change = index_csv([("2021-05-21", "100", "110", "90", "105")]).replace(b",5,", b",4,")
    [record] = parse_index_file(COMPOSITE, bad_change)
    assert record.values is None and "change_differs_from_close_minus_previous" in record.reasons
    [outside] = parse_index_file(COMPOSITE, index_csv([("2021-05-21", "100", "110", "90", "120")]))
    assert outside.values is None and "close_outside_high_low" in outside.reasons
    with pytest.raises(StructuralError, match="unexpected header"):
        parse_index_file(COMPOSITE, b"Date,Close\r\n2021-05-21,1\r\n")
    source = PholenkIndexSource()
    with pytest.raises(StructuralError, match="unexpected files"):
        source.select_data_files([COMPOSITE, "dataset/indices/csv/notes.txt"])
    assert source.select_data_files([COMPOSITE, "dataset/preview/indices/csv/ABX.csv"]) == (
        COMPOSITE,
    )


def test_index_returns_mark_breaks_unreliable() -> None:
    rows = [
        (date(2021, 5, 21), Decimal("5840"), Decimal("5800"), []),
        (date(2021, 5, 22), Decimal("5920"), Decimal("5840"), ["unverified_trading_date"]),
        (date(2021, 5, 24), Decimal("5900"), Decimal("5773"), []),
        (date(2021, 5, 25), Decimal("5940"), Decimal("5900"), []),
    ]
    bars = index_returns(rows)
    assert [b.reliable for b in bars] == [True, False, False, True]
    assert bars[3].index_return == Decimal("5940") / Decimal("5900") - 1


# --------------------------------------------------------------------------
# Database
# --------------------------------------------------------------------------


@pytest.fixture
def engine(migrated_database: Engine) -> Engine:
    with migrated_database.begin() as conn:
        conn.execute(text(f"TRUNCATE {TABLES} RESTART IDENTITY"))
    return migrated_database


def load_indices(engine: Engine, root: Path) -> Any:
    prepared = prepare_record_snapshot(PholenkIndexSource(), root)
    return RecordLoader(engine, price_source_id="unused").load(prepared, confirm_revision=REVISION)


@pytest.mark.integration
def test_indices_load_into_the_registered_price_snapshot(tmp_path: Path, engine: Engine) -> None:
    root = snapshot(tmp_path / "s")
    prices = load(engine, root)
    first = load_indices(engine, root)
    assert first.snapshot_id == prices.snapshot_id  # same snapshot, new run
    assert (first.counters.rows_inserted, first.counters.files_processed) == (5, 2)
    with engine.connect() as conn:
        snapshots = conn.execute(text("SELECT count(*) FROM source_snapshots")).scalar_one()
        runs = conn.execute(text("SELECT parser_version FROM ingestion_runs ORDER BY 1")).scalars()
        line = conn.execute(
            text(
                "SELECT source_line FROM index_daily_values "
                "WHERE index_code = 'COMPOSITE' AND trading_date = '2021-05-25'"
            )
        ).scalar_one()
    assert snapshots == 1 and list(runs) == ["pholenk-csv-2", "pholenk-index-csv-1"]
    assert line == 2
    again = load_indices(engine, root)
    assert (again.counters.rows_inserted, again.counters.rows_unchanged) == (0, 5)
    with pytest.raises(LoadNotConfirmedError):
        RecordLoader(engine, price_source_id="unused").load(
            prepare_record_snapshot(PholenkIndexSource(), root), confirm_revision="9bb3b26"
        )


@pytest.mark.integration
def test_observed_trading_days_view(tmp_path: Path, engine: Engine) -> None:
    root = snapshot(tmp_path / "s")
    load(engine, root)
    load_indices(engine, root)
    with engine.connect() as conn:
        days = {
            r.trading_date: r
            for r in conn.execute(text("SELECT * FROM observed_trading_days ORDER BY 2"))
        }
    assert set(days) == {date(2021, 5, d) for d in (21, 22, 24, 25)}
    missing = days[date(2021, 5, 25)]
    assert (missing.in_stock_data, missing.in_index_data, missing.stock_rows) == (False, True, 0)
    assert days[date(2021, 5, 22)].is_weekend and not days[date(2021, 5, 21)].is_weekend
    assert (days[date(2021, 5, 21)].stock_rows, days[date(2021, 5, 21)].index_rows) == (2, 2)


@pytest.mark.integration
def test_benchmark_series_and_verification(tmp_path: Path, engine: Engine) -> None:
    root = snapshot(tmp_path / "s")
    load(engine, root)
    load_indices(engine, root)
    with engine.connect() as conn:
        bars = load_index_series(conn)
    assert [b.reliable for b in bars] == [True, False, False, True]
    report = verify_records(engine, prepare_record_snapshot(PholenkIndexSource(), root), deep=True)
    assert report.ok, [(c.name, c.expected, c.actual) for c in report.failures]
    # the price verification still selects the price run, not the index run
    price_report = verify(engine, prepare_snapshot(PholenkSnapshotSource(), root))
    assert price_report.ok, [(c.name, c.expected, c.actual) for c in price_report.failures]
    with engine.begin() as conn:
        conn.execute(
            text(
                "UPDATE index_daily_values SET close = close + 1, high = high + 1 "
                "WHERE index_code = 'LQ45'"
            )
        )
    tampered = verify_records(
        engine, prepare_record_snapshot(PholenkIndexSource(), root), deep=True
    )
    assert {c.name: c.actual for c in tampered.failures} == {"observation_differs": 1}


# --------------------------------------------------------------------------
# Schema
# --------------------------------------------------------------------------


def test_index_table_metadata() -> None:
    table = metadata.tables["index_daily_values"]
    assert [c.name for c in table.primary_key.columns] == [
        "source_id",
        "index_code",
        "trading_date",
    ]
    assert {fk.ondelete for fk in table.foreign_keys} == {"RESTRICT"} and len(
        table.foreign_keys
    ) == 3


@pytest.mark.integration
def test_index_constraints(tmp_path: Path, engine: Engine) -> None:
    root = snapshot(tmp_path / "s")
    load(engine, root)
    load_indices(engine, root)
    with engine.connect() as c:
        base = dict(
            c.execute(text("SELECT * FROM index_daily_values WHERE index_code = 'LQ45'"))
            .mappings()
            .one()
        )
    base["trading_date"] = date(2021, 5, 28)
    for overrides, constraint in (
        ({"high": Decimal("1")}, "high_low_close_shape"),
        ({"previous": Decimal("0")}, "values_positive"),
        ({"quality_flags": ["made_up"]}, "quality_flags_vocabulary"),
        ({"index_code": "bad code"}, "index_code_format"),
    ):
        with engine.connect() as c, pytest.raises(IntegrityError, match=constraint):
            c.execute(insert(IndexDailyValue).values(**{**base, **overrides}))


@pytest.mark.integration
def test_migration_round_trip_keeps_view(engine: Engine) -> None:
    config = Config(str(ALEMBIC_INI))
    with engine.begin() as connection:
        config.attributes["connection"] = connection
        command.downgrade(config, "55a78b2c9066")
        names = inspect(connection)
        assert "index_daily_values" not in names.get_table_names()
        assert "observed_trading_days" not in names.get_view_names()
        command.upgrade(config, "head")
        names = inspect(connection)
        assert "index_daily_values" in names.get_table_names()
        assert "observed_trading_days" in names.get_view_names()
