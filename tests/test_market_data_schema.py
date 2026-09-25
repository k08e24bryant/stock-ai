"""Phase 2B.2 schema tests: model metadata and database-level constraints.

Metadata tests need no database. Constraint tests are marked ``integration``:
they run against a throwaway database migrated to ``head`` by the real
migration (the ``migrated_database`` fixture in ``conftest.py``), never the
development database. Each test runs inside a transaction that is always
rolled back, and each expected failure runs in its own savepoint and asserts
*which* constraint fired.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

import pytest
from sqlalchemy import Connection, Engine, Float, Numeric, delete, insert, select
from sqlalchemy.exc import IntegrityError

from backend.models import (
    DailyPrice,
    DataQualityIncident,
    DataSource,
    IngestionRun,
    Security,
    SecuritySourceKey,
    SourceFile,
    SourceSnapshot,
    metadata,
)

SOURCE_ID = "test-source"
REVISION = "rev1"
CONTENT = "a" * 64
SNAPSHOT_ID = f"{SOURCE_ID}:{REVISION}:{CONTENT[:16]}"

# --------------------------------------------------------------------------
# Metadata (no database)
# --------------------------------------------------------------------------


PHASE_2B_TABLES = {
    "data_sources",
    "source_snapshots",
    "source_files",
    "ingestion_runs",
    "securities",
    "security_source_keys",
    "daily_prices",
    "data_quality_incidents",
}


def test_all_eight_tables_are_registered() -> None:
    assert set(metadata.tables) >= PHASE_2B_TABLES


def test_daily_prices_key_and_excluded_columns() -> None:
    table = metadata.tables["daily_prices"]
    assert list(table.primary_key.columns.keys()) == ["security_id", "trading_date", "source_id"]
    excluded = {
        "is_adjusted",
        "price_basis",
        "snapshot_id",
        "content_hash",
        "created_at",
        "available_at",
    }
    assert excluded.isdisjoint(table.columns.keys())
    assert table.columns["open"].nullable and table.columns["high"].nullable
    assert not table.columns["close"].nullable


def test_every_foreign_key_restricts_delete() -> None:
    fks = [fk for name in PHASE_2B_TABLES for fk in metadata.tables[name].foreign_keys]
    assert len(fks) == 14
    assert {fk.ondelete for fk in fks} == {"RESTRICT"}


def test_numeric_types_are_exact() -> None:
    cols = metadata.tables["daily_prices"].columns

    def precision_scale(name: str) -> tuple[int | None, int | None]:
        column_type = cols[name].type
        assert isinstance(column_type, Numeric) and not isinstance(column_type, Float)
        return column_type.precision, column_type.scale

    for name in ("open", "high", "low", "close", "reference_price"):
        assert precision_scale(name) == (20, 4)
    assert precision_scale("value") == (24, 4)
    assert cols["volume"].type.python_type is int
    assert cols["frequency"].type.python_type is int


def test_minimal_indexes() -> None:
    names = {ix.name for name in PHASE_2B_TABLES for ix in metadata.tables[name].indexes}
    assert names == {
        "ix_daily_prices_trading_date",
        "ix_ingestion_runs_snapshot_id",
        "ix_securities_ticker",
        "ix_security_source_keys_security_id",
        "ix_data_quality_incidents_ingestion_run_id",
        "ix_data_quality_incidents_security_id_trading_date",
    }


# --------------------------------------------------------------------------
# Database constraints (integration)
# --------------------------------------------------------------------------


@pytest.fixture
def conn(migrated_database: Engine) -> Iterator[Connection]:
    """A connection whose outer transaction is always rolled back."""
    with migrated_database.connect() as connection:
        transaction = connection.begin()
        try:
            yield connection
        finally:
            transaction.rollback()


class Seed:
    """Parent rows every daily-price test needs."""

    def __init__(self, conn: Connection) -> None:
        self.conn = conn
        conn.execute(insert(DataSource).values(source_id=SOURCE_ID, source_name="Test"))
        conn.execute(insert(SourceSnapshot).values(**snapshot_values()))
        self.file_id: int = conn.execute(
            insert(SourceFile)
            .values(
                snapshot_id=SNAPSHOT_ID,
                relative_path="dataset/stocks/csv/BBCA.csv",
                sha256="b" * 64,
                row_count=3,
                source_key="BBCA",
            )
            .returning(SourceFile.file_id)
        ).scalar_one()
        self.run_id = uuid.uuid4()
        conn.execute(
            insert(IngestionRun).values(
                ingestion_run_id=self.run_id,
                snapshot_id=SNAPSHOT_ID,
                parser_version="test-1",
                started_at=datetime(2026, 9, 24, tzinfo=UTC),
                status="running",
            )
        )
        self.security_id: int = conn.execute(
            insert(Security)
            .values(ticker="BBCA", name="Bank Central Asia Tbk.", identity_kind="development")
            .returning(Security.security_id)
        ).scalar_one()
        conn.execute(
            insert(SecuritySourceKey).values(
                source_id=SOURCE_ID,
                source_key="BBCA",
                security_id=self.security_id,
                first_seen_snapshot_id=SNAPSHOT_ID,
            )
        )

    def price(self, **overrides: Any) -> dict[str, Any]:
        """A valid traded row; override any column."""
        values: dict[str, Any] = {
            "security_id": self.security_id,
            "trading_date": date(2026, 5, 29),
            "source_id": SOURCE_ID,
            "open": Decimal("5750"),
            "high": Decimal("5875"),
            "low": Decimal("5700"),
            "close": Decimal("5700"),
            "reference_price": Decimal("5975"),
            "volume": 1_015_296_600,
            "value": Decimal("5822702632500"),
            "frequency": 111_208,
            "trading_status": "traded",
            "file_id": self.file_id,
            "source_line": 2,
            "ingestion_run_id": self.run_id,
        }
        values.update(overrides)
        return values

    def no_trade(self, **overrides: Any) -> dict[str, Any]:
        base = self.price(
            open=None,
            high=None,
            low=None,
            close=Decimal("535"),
            reference_price=Decimal("535"),
            volume=0,
            value=Decimal("0"),
            frequency=0,
            trading_status="no_regular_market_trade",
        )
        base.update(overrides)
        return base

    def insert_price(self, values: dict[str, Any]) -> None:
        self.conn.execute(insert(DailyPrice).values(**values))

    def rejects(self, values: dict[str, Any], constraint: str) -> None:
        """Insert must fail on `constraint`; the savepoint keeps the test usable."""
        with pytest.raises(IntegrityError, match=constraint), self.conn.begin_nested():
            self.insert_price(values)


def snapshot_values(**overrides: Any) -> dict[str, Any]:
    values: dict[str, Any] = {
        "snapshot_id": SNAPSHOT_ID,
        "source_id": SOURCE_ID,
        "source_revision": REVISION,
        "content_sha256": CONTENT,
        "archive_sha256": "c" * 64,
        "source_url": "https://example.invalid/dataset",
        "retrieved_at": datetime(2026, 9, 24, 11, 28, 14, tzinfo=UTC),
        "licence_reference": "test licence",
        "raw_storage_path": "data/raw/test",
        "file_count": 1,
    }
    values.update(overrides)
    return values


@pytest.fixture
def seed(conn: Connection) -> Seed:
    return Seed(conn)


def fetch(seed: Seed) -> Any:
    return seed.conn.execute(
        select(DailyPrice).where(DailyPrice.security_id == seed.security_id)
    ).one()


# 1-2. valid TRADED rows, with and without an open ---------------------------


@pytest.mark.integration
def test_valid_traded_row_with_open(seed: Seed) -> None:
    seed.insert_price(seed.price())
    row = fetch(seed)
    assert row.open == Decimal("5750") and row.quality_flags == []


@pytest.mark.integration
def test_valid_traded_row_with_null_open_is_accepted(seed: Seed) -> None:
    seed.insert_price(seed.price(open=None))
    assert fetch(seed).open is None


# 3. valid NO_REGULAR_MARKET_TRADE row ---------------------------------------


@pytest.mark.integration
def test_valid_no_regular_market_trade_row(seed: Seed) -> None:
    seed.insert_price(seed.no_trade(quality_flags=["non_regular_activity_present"]))
    row = fetch(seed)
    assert (row.open, row.high, row.low, row.volume) == (None, None, None, 0)
    assert row.close == Decimal("535")


@pytest.mark.integration
def test_unknown_status_only_needs_general_constraints(seed: Seed) -> None:
    seed.insert_price(seed.price(trading_status="unknown", volume=0, open=None))


# 4-5. negative price and volume ---------------------------------------------


@pytest.mark.integration
@pytest.mark.parametrize(
    ("column", "constraint"),
    [
        ("open", "ck_daily_prices_open_positive"),
        ("high", "ck_daily_prices_high_positive"),
        ("low", "ck_daily_prices_low_positive"),
        ("close", "ck_daily_prices_close_positive"),
        ("reference_price", "ck_daily_prices_reference_price_positive"),
    ],
)
def test_non_positive_price_rejected(seed: Seed, column: str, constraint: str) -> None:
    seed.rejects(seed.price(trading_status="unknown", **{column: Decimal("-1")}), constraint)


@pytest.mark.integration
def test_negative_volume_rejected(seed: Seed) -> None:
    seed.rejects(
        seed.price(trading_status="unknown", volume=-1), "ck_daily_prices_volume_non_negative"
    )


# 6. TRADED shape --------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.parametrize(
    "overrides",
    [
        {"volume": 0},
        {"volume": None},  # NULL must not slip through three-valued logic
        {"high": None},
        {"low": None},
        {"high": Decimal("5600")},  # high < low
        {"close": Decimal("5900")},  # high < close
        {"close": Decimal("5650"), "low": Decimal("5700")},  # low > close
        {"open": Decimal("5900")},  # open > high
        {"open": Decimal("5650")},  # open < low
    ],
)
def test_invalid_traded_rows_rejected(seed: Seed, overrides: dict[str, Any]) -> None:
    seed.rejects(seed.price(**overrides), "ck_daily_prices_traded_shape")


# 7. NO_REGULAR_MARKET_TRADE shape ---------------------------------------------


@pytest.mark.integration
@pytest.mark.parametrize(
    "overrides",
    [
        {"open": Decimal("535")},
        {"high": Decimal("540")},
        {"low": Decimal("530")},
        {"volume": 100},
        {"volume": None},
    ],
)
def test_invalid_no_regular_trade_rows_rejected(seed: Seed, overrides: dict[str, Any]) -> None:
    seed.rejects(seed.no_trade(**overrides), "ck_daily_prices_no_regular_trade_shape")


# 8. trading-status vocabulary ---------------------------------------------------


@pytest.mark.integration
@pytest.mark.parametrize("status", ["TRADED", "suspended", "no_trade_or_suspended", ""])
def test_undocumented_trading_status_rejected(seed: Seed, status: str) -> None:
    seed.rejects(seed.price(trading_status=status), "ck_daily_prices_trading_status_vocabulary")


# quality flags --------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.parametrize("flags", [["suspended"], ["unverified_trading_date", None]])
def test_undocumented_or_null_quality_flag_rejected(seed: Seed, flags: list[Any]) -> None:
    seed.rejects(seed.price(quality_flags=flags), "ck_daily_prices_quality_flags_vocabulary")


@pytest.mark.integration
def test_source_key_quality_flag_vocabulary(seed: Seed) -> None:
    ok = {"source_id": SOURCE_ID, "security_id": seed.security_id}
    seed.conn.execute(
        insert(SecuritySourceKey).values(
            source_key="TRUE",
            first_seen_snapshot_id=SNAPSHOT_ID,
            quality_flags=["source_ticker_column_mismatch"],
            **ok,
        )
    )
    with (
        pytest.raises(IntegrityError, match="ck_security_source_keys_quality_flags_vocabulary"),
        seed.conn.begin_nested(),
    ):
        seed.conn.execute(
            insert(SecuritySourceKey).values(
                source_key="XXXX",
                first_seen_snapshot_id=SNAPSHOT_ID,
                quality_flags=["non_regular_activity_present"],
                **ok,
            )
        )


# 9-11. uniqueness --------------------------------------------------------------------


@pytest.mark.integration
def test_duplicate_daily_price_key_rejected(seed: Seed) -> None:
    seed.insert_price(seed.price())
    seed.rejects(seed.price(close=Decimal("5725")), "pk_daily_prices")


@pytest.mark.integration
def test_duplicate_source_key_rejected(seed: Seed) -> None:
    with pytest.raises(IntegrityError, match="pk_security_source_keys"), seed.conn.begin_nested():
        seed.conn.execute(
            insert(SecuritySourceKey).values(
                source_id=SOURCE_ID,
                source_key="BBCA",
                security_id=seed.security_id,
                first_seen_snapshot_id=SNAPSHOT_ID,
            )
        )


@pytest.mark.integration
def test_duplicate_snapshot_file_path_rejected(seed: Seed) -> None:
    with (
        pytest.raises(IntegrityError, match="uq_source_files_snapshot_id"),
        seed.conn.begin_nested(),
    ):
        seed.conn.execute(
            insert(SourceFile).values(
                snapshot_id=SNAPSHOT_ID,
                relative_path="dataset/stocks/csv/BBCA.csv",
                sha256="d" * 64,
                row_count=1,
            )
        )


# snapshot identity ------------------------------------------------------------------


@pytest.mark.integration
def test_snapshot_identity_is_derived_and_retrieval_time_is_not_identity(seed: Seed) -> None:
    same_identity_other_retrieval = snapshot_values(
        snapshot_id="different-id",
        retrieved_at=datetime(2027, 1, 1, tzinfo=UTC),
    )
    with pytest.raises(IntegrityError, match="snapshot_id_derived"), seed.conn.begin_nested():
        seed.conn.execute(insert(SourceSnapshot).values(**same_identity_other_retrieval))
    with pytest.raises(IntegrityError, match="pk_source_snapshots"), seed.conn.begin_nested():
        seed.conn.execute(
            insert(SourceSnapshot).values(
                **snapshot_values(retrieved_at=datetime(2027, 1, 1, tzinfo=UTC))
            )
        )
    bad = snapshot_values(
        snapshot_id=f"{SOURCE_ID}:r2:NOT-A-HASH-VALUE",
        source_revision="r2",
        content_sha256="NOT-A-HASH-VALUE",
    )
    with pytest.raises(IntegrityError, match="content_sha256_format"), seed.conn.begin_nested():
        seed.conn.execute(insert(SourceSnapshot).values(**bad))


@pytest.mark.integration
def test_many_runs_per_snapshot_and_run_status_consistency(seed: Seed) -> None:
    run = {
        "snapshot_id": SNAPSHOT_ID,
        "parser_version": "test-1",
        "started_at": datetime(2026, 9, 24, tzinfo=UTC),
    }
    seed.conn.execute(
        insert(IngestionRun).values(
            ingestion_run_id=uuid.uuid4(),
            status="succeeded",
            completed_at=datetime(2026, 9, 24, 1, tzinfo=UTC),
            **run,
        )
    )
    with pytest.raises(IntegrityError, match="completion_matches_status"), seed.conn.begin_nested():
        seed.conn.execute(
            insert(IngestionRun).values(ingestion_run_id=uuid.uuid4(), status="succeeded", **run)
        )


# numeric capacity ---------------------------------------------------------------------


@pytest.mark.integration
def test_measured_maxima_fit(seed: Seed) -> None:
    """Phase 2A.5 maxima: volume 45,941,761,600; value 9,804,286,370,000; price 398,000."""
    seed.insert_price(
        seed.price(
            high=Decimal("398000"),
            open=Decimal("359925"),
            low=Decimal("346825"),
            close=Decimal("359900"),
            volume=45_941_761_600,
            value=Decimal("9804286370000"),
            frequency=530_819,
        )
    )
    row = fetch(seed)
    assert row.volume == 45_941_761_600 and row.value == Decimal("9804286370000")


# referential integrity -------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.parametrize(
    ("overrides", "constraint"),
    [
        ({"security_id": 999_999_999}, "fk_daily_prices_security_id_securities"),
        ({"file_id": 999_999_999}, "fk_daily_prices_file_id_source_files"),
        ({"source_id": "no-such-source"}, "fk_daily_prices_source_id_data_sources"),
        ({"ingestion_run_id": uuid.uuid4()}, "fk_daily_prices_ingestion_run_id_ingestion_runs"),
    ],
)
def test_foreign_keys_enforced(seed: Seed, overrides: dict[str, Any], constraint: str) -> None:
    seed.rejects(seed.price(**overrides), constraint)


@pytest.mark.integration
def test_deleting_referenced_parents_is_restricted(seed: Seed) -> None:
    seed.insert_price(seed.price())
    # Any referencing foreign key may be reported first; each must be a RESTRICT.
    for statement, constraint in (
        (delete(Security), r"fk_\w+_security_id_securities"),
        (delete(SourceFile), r"fk_\w+_file_id_source_files"),
        (delete(SourceSnapshot), r"fk_\w+_source_snapshots"),
        (delete(DataSource), r"fk_\w+_data_sources"),
    ):
        with pytest.raises(IntegrityError, match=constraint), seed.conn.begin_nested():
            seed.conn.execute(statement)


@pytest.mark.integration
def test_incident_records_details_without_touching_prices(seed: Seed) -> None:
    seed.conn.execute(
        insert(DataQualityIncident).values(
            ingestion_run_id=seed.run_id,
            incident_type="source_ticker_column_mismatch",
            severity="warning",
            source_id=SOURCE_ID,
            file_id=seed.file_id,
            source_line=2,
            details={"raw_ticker": "True", "source_key": "TRUE"},
        )
    )
    status = seed.conn.execute(select(DataQualityIncident.status)).scalar_one()
    assert status == "open"
    with pytest.raises(IntegrityError, match="incident_type_vocabulary"), seed.conn.begin_nested():
        seed.conn.execute(
            insert(DataQualityIncident).values(
                ingestion_run_id=seed.run_id, incident_type="made_up", severity="info", details={}
            )
        )
