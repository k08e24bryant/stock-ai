"""Phase 2C-2 schema: metadata tripwires, database CHECKs, and migration round trip.

Constraint tests run in a throwaway database (``migrated_database``) inside a
transaction that is always rolled back; each expected failure runs in its own
savepoint and asserts *which* constraint fired.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Connection, Engine, insert, inspect
from sqlalchemy.exc import IntegrityError
from test_market_data_schema import SOURCE_ID, Seed

from backend.models import (
    AdjustmentBuild,
    CashDividend,
    DataQualityIncident,
    PriceAdjustmentFactor,
    metadata,
)

ALEMBIC_INI = Path(__file__).resolve().parents[1] / "alembic.ini"
PHASE_2C_TABLES = {
    "corporate_action_events",
    "cash_dividends",
    "adjustment_builds",
    "price_adjustment_factors",
    "reference_price_anomaly_dates",
}


def test_phase_2c_tables_foreign_keys_and_indexes() -> None:
    assert set(metadata.tables) >= PHASE_2C_TABLES
    fks = [fk for name in PHASE_2C_TABLES for fk in metadata.tables[name].foreign_keys]
    assert len(fks) == 17
    assert {fk.ondelete for fk in fks} == {"RESTRICT"}
    names = {ix.name for name in PHASE_2C_TABLES for ix in metadata.tables[name].indexes}
    assert names == {
        "ix_cash_dividends_security_id_ex_date",
        "ix_corporate_action_events_security_id_date",
    }
    assert "adj_close" not in metadata.tables["daily_prices"].columns  # raw stays raw


@pytest.fixture
def conn(migrated_database: Engine) -> Iterator[Connection]:
    with migrated_database.connect() as connection:
        transaction = connection.begin()
        try:
            yield connection
        finally:
            transaction.rollback()


@pytest.fixture
def seed(conn: Connection) -> Seed:
    return Seed(conn)


def rejects(conn: Connection, model: Any, values: dict[str, Any], constraint: str) -> None:
    with pytest.raises(IntegrityError, match=constraint), conn.begin_nested():
        conn.execute(insert(model).values(**values))


def dividend(seed: Seed, **overrides: Any) -> dict[str, Any]:
    values: dict[str, Any] = {
        "source_id": SOURCE_ID,
        "source_ticker": "BBCA.JK",
        "ex_date": date(2024, 5, 2),
        "security_id": seed.security_id,
        "security_match": "ticker_text_match",
        "amount": Decimal("227.5"),
        "amount_basis": "unstated",
        "dividend_type": "final",
        "fiscal_year": 2023,
        "file_id": seed.file_id,
        "record_ref": "BBCA.JK[0]",
        "ingestion_run_id": seed.run_id,
    }
    values.update(overrides)
    return values


def factor(seed: Seed, build_id: uuid.UUID, **overrides: Any) -> dict[str, Any]:
    values: dict[str, Any] = {
        "price_source_id": SOURCE_ID,
        "method_version": "ref-v1",
        "security_id": seed.security_id,
        "effective_date": date(2021, 10, 13),
        "factor_kind": "price",
        "build_id": build_id,
        "factor": Decimal("0.2"),
        "classification": "split",
        "status": "applied",
        "reference_price": Decimal("7325"),
        "close": Decimal("7525"),
        "prev_trading_date": date(2021, 10, 12),
        "prev_close": Decimal("36600"),
        "file_id": seed.file_id,
        "source_line": 3,
    }
    values.update(overrides)
    return values


@pytest.mark.integration
def test_dividend_constraints(conn: Connection, seed: Seed) -> None:
    conn.execute(insert(CashDividend).values(**dividend(seed)))
    next_day = {"ex_date": date(2024, 5, 3)}
    rejects(conn, CashDividend, dividend(seed, **next_day, amount=0), "amount_positive")
    rejects(
        conn,
        CashDividend,
        dividend(seed, ex_date=date(2024, 5, 3), security_match="unmatched"),
        "security_match_consistent",
    )
    rejects(
        conn,
        CashDividend,
        dividend(seed, ex_date=date(2024, 5, 3), amount_basis="probably_gross"),
        "amount_basis_vocabulary",
    )
    rejects(conn, CashDividend, dividend(seed), "uq_cash_dividends_source_id")


@pytest.mark.integration
def test_factor_constraints(conn: Connection, seed: Seed) -> None:
    build_id = uuid.uuid4()
    conn.execute(
        insert(AdjustmentBuild).values(
            build_id=build_id,
            price_source_id=SOURCE_ID,
            method_version="ref-v1",
            parameters={},
            inputs={},
            summary={},
        )
    )
    conn.execute(insert(PriceAdjustmentFactor).values(**factor(seed, build_id)))
    other = {"effective_date": date(2022, 1, 3)}
    rejects(
        conn, PriceAdjustmentFactor, factor(seed, build_id, **other, factor=0), "factor_positive"
    )
    rejects(
        conn,
        PriceAdjustmentFactor,
        factor(seed, build_id, **other, classification="cash_dividend"),
        "classification_matches_kind",
    )
    rejects(
        conn,
        PriceAdjustmentFactor,
        factor(seed, build_id, **other, prev_close=None),
        "price_factor_has_previous_row",
    )
    rejects(
        conn,
        PriceAdjustmentFactor,
        factor(
            seed, build_id, **other, factor_kind="cash_dividend", classification="cash_dividend"
        ),
        "dividend_amount_iff_dividend",
    )
    rejects(
        conn,
        PriceAdjustmentFactor,
        factor(seed, build_id, **other, status="maybe"),
        "status_vocabulary",
    )


@pytest.mark.integration
def test_incident_type_vocabulary_includes_malformed_optional_field(
    conn: Connection, seed: Seed
) -> None:
    ok = {
        "ingestion_run_id": seed.run_id,
        "severity": "warning",
        "source_id": SOURCE_ID,
        "details": {"field": "payment_date"},
    }
    conn.execute(insert(DataQualityIncident).values(**ok, incident_type="malformed_optional_field"))
    bogus = {**ok, "incident_type": "made_up"}
    rejects(conn, DataQualityIncident, bogus, "incident_type_vocabulary")


@pytest.mark.integration
def test_migration_downgrades_and_upgrades_cleanly(migrated_database: Engine) -> None:
    config = Config(str(ALEMBIC_INI))
    with migrated_database.begin() as connection:
        config.attributes["connection"] = connection
        command.downgrade(config, "1c1d7048b74f")
        assert PHASE_2C_TABLES.isdisjoint(inspect(connection).get_table_names())
        command.upgrade(config, "head")
        assert set(inspect(connection).get_table_names()) >= PHASE_2C_TABLES
