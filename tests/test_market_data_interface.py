"""Tests for the provider-neutral market-data interface (no providers exist yet)."""

from __future__ import annotations

import dataclasses
from collections.abc import Sequence
from datetime import UTC, date, datetime
from decimal import Decimal

import pytest

from data.ingestion import provider as p


def _provenance() -> p.Provenance:
    now = datetime(2026, 9, 24, tzinfo=UTC)
    return p.Provenance(
        source_id="example",
        source_security_id="BBCA",
        retrieved_at=now,
        ingestion_run_id="run-1",
        raw_record_ref="raw/example/BBCA.csv#sha256=0",
        licence_ref="https://example.invalid/licence (read 2026-09-24)",
        parser_version="0",
        available_at=now,
        available_at_is_fallback=True,
    )


class _StubProvider:
    """Structural stand-in used only to check the Protocol shape."""

    def list_securities(self) -> Sequence[p.Security]:
        return []

    def get_daily_prices(
        self, source_security_id: str, start: date, end: date
    ) -> list[p.DailyPrice]:
        return []

    def get_dividends(self, source_security_id: str, start: date, end: date) -> list[p.Dividend]:
        return []

    def get_corporate_actions(
        self, source_security_id: str, start: date, end: date
    ) -> list[p.CorporateAction]:
        return []

    def get_index_history(self, index_code: str, start: date, end: date) -> list[p.IndexLevel]:
        return []


def test_stub_satisfies_protocol() -> None:
    assert isinstance(_StubProvider(), p.MarketDataProvider)


def test_object_missing_methods_does_not_satisfy_protocol() -> None:
    assert not isinstance(object(), p.MarketDataProvider)


def test_records_are_immutable_and_carry_provenance() -> None:
    price = p.DailyPrice(
        source_security_id="BBCA",
        ticker="BBCA",
        trade_date=date(2026, 5, 29),
        close=Decimal("5700"),
        price_basis=p.PriceBasis.RAW,
        trading_status=p.TradingStatus.TRADED,
        provenance=_provenance(),
    )
    assert price.open is None  # some public sources do not supply opens
    assert price.is_adjusted is False
    assert price.currency == "IDR"
    with pytest.raises(dataclasses.FrozenInstanceError):
        price.close = Decimal("1")  # type: ignore[misc]


def test_every_record_type_requires_provenance() -> None:
    for record in (p.Security, p.DailyPrice, p.Dividend, p.CorporateAction, p.IndexLevel):
        field = {f.name: f for f in dataclasses.fields(record)}["provenance"]
        assert field.default is dataclasses.MISSING


def test_interface_module_defines_no_concrete_provider() -> None:
    """Concrete providers live in their own modules (e.g. data/ingestion/pholenk.py)."""
    implementations = [
        obj
        for obj in vars(p).values()
        if isinstance(obj, type)
        and obj is not p.MarketDataProvider
        and hasattr(obj, "get_daily_prices")
    ]
    assert implementations == []
