"""Tests for the Pholenk development provider, using small synthetic fixtures.

No network access and no real dataset: each test writes CSV files with the
verified Pholenk structure (UTF-8 BOM, 26 columns, newest date first).
"""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import UTC, date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import pytest

from data.ingestion.pholenk import (
    EXPECTED_COLUMNS,
    SOURCE_ID,
    DuplicateRecordError,
    PholenkFormatError,
    PholenkProvider,
    PholenkValidationError,
    UnknownSecurityError,
    development_security_id,
    normalize_trade_date,
    source_key,
)
from data.ingestion.provider import MarketDataProvider, NotProvidedError, PriceBasis, TradingStatus
from data.validation.daily_prices import Severity, build_quality_report, validate_daily_price

RETRIEVED_AT = datetime(2026, 9, 24, 11, 28, 14, tzinfo=UTC)
REVISION = "9bb3b26bd28ab46bc2f3e74a7c03805ce053301b"
FULL_RANGE = (date(1900, 1, 1), date(2100, 1, 1))


def row(**overrides: str) -> dict[str, str]:
    """A valid traded row; override any column by name."""
    base = {column: "0" for column in EXPECTED_COLUMNS}
    base.update(
        Date="2026-05-29",
        Ticker="BBCA",
        Name="Bank Central Asia Tbk.",
        Remarks="--MO1UQNCNU600G111------------",
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


def write_stock(root: Path, key: str, rows: list[dict[str, str]]) -> Path:
    directory = root / "dataset" / "stocks" / "csv"
    directory.mkdir(parents=True, exist_ok=True)
    lines = [",".join(EXPECTED_COLUMNS)]
    lines += [",".join(r[c] for c in EXPECTED_COLUMNS) for r in rows]
    path = directory / f"{key}.csv"
    path.write_bytes(b"\xef\xbb\xbf" + ("\r\n".join(lines) + "\r\n").encode("utf-8"))
    return path


def provider(root: Path) -> PholenkProvider:
    return PholenkProvider(root, retrieved_at=RETRIEVED_AT, revision=REVISION)


BBCA = development_security_id("BBCA")


# 1. valid traded row -------------------------------------------------------


def test_valid_traded_row(tmp_path: Path) -> None:
    write_stock(tmp_path, "BBCA", [row()])
    [price] = provider(tmp_path).get_daily_prices(BBCA, *FULL_RANGE)
    assert price.trading_status is TradingStatus.TRADED
    assert (price.open, price.high, price.low, price.close) == (
        Decimal("5750.0"),
        Decimal("5875.0"),
        Decimal("5700.0"),
        Decimal("5700.0"),
    )
    assert price.volume_shares == 1015296600
    assert price.previous_close == Decimal("5975.0")
    assert price.ticker == "BBCA"
    assert validate_daily_price(price) == ()


# 2. missing open ----------------------------------------------------------


def test_open_zero_becomes_none_and_is_not_replaced(tmp_path: Path) -> None:
    write_stock(tmp_path, "BBCA", [row(Open="0.0")])
    [price] = provider(tmp_path).get_daily_prices(BBCA, *FULL_RANGE)
    assert price.open is None
    assert price.close == Decimal("5700.0")  # close untouched, never copied into open
    issues = validate_daily_price(price)
    assert [i.code for i in issues] == ["open_missing"]
    assert issues[0].severity is Severity.EXPECTED_SOURCE_CONDITION


# 3. zero-volume / no-trade row ---------------------------------------------


def test_zero_volume_row_is_kept_with_uncertain_status(tmp_path: Path) -> None:
    no_trade = row(
        Date="2021-10-06", Open="0.0", High="0.0", Low="0.0", Close="535.0",
        Previous="535.0", Volume="0", Value="0", Frequency="0",
    )  # fmt: skip
    write_stock(tmp_path, "BBCA", [no_trade])
    [price] = provider(tmp_path).get_daily_prices(BBCA, *FULL_RANGE)
    assert price.trading_status is TradingStatus.NO_TRADE_OR_SUSPENDED  # not claimed SUSPENDED
    assert (price.open, price.high, price.low) == (None, None, None)
    assert price.close == Decimal("535.0")
    assert price.volume_shares == 0
    codes = {i.code: i.severity for i in validate_daily_price(price)}
    assert codes == {
        "no_trade_or_suspended": Severity.EXPECTED_SOURCE_CONDITION,
        "open_missing": Severity.EXPECTED_SOURCE_CONDITION,
    }


# 4. invalid OHLC -----------------------------------------------------------


@pytest.mark.parametrize(
    ("overrides", "code"),
    [
        ({"High": "5600.0"}, "high_below_low"),
        ({"Close": "5900.0"}, "high_below_close"),
        ({"Open": "5900.0"}, "high_below_open"),
        ({"Open": "5650.0"}, "low_above_open"),
        ({"Close": "5650.0", "Low": "5700.0"}, "low_above_close"),
    ],
)
def test_invalid_ohlc_fails_loudly(tmp_path: Path, overrides: dict[str, str], code: str) -> None:
    write_stock(tmp_path, "BBCA", [row(**overrides)])
    p = provider(tmp_path)
    with pytest.raises(PholenkValidationError, match=code):
        p.get_daily_prices(BBCA, *FULL_RANGE)
    report = build_quality_report(p.normalized_prices(BBCA))
    assert report.invalid_ohlc_count == 1
    assert report.hard_invalid_rows == 1


# 5. negative volume --------------------------------------------------------


def test_negative_volume_fails_loudly(tmp_path: Path) -> None:
    write_stock(tmp_path, "BBCA", [row(Volume="-5")])
    p = provider(tmp_path)
    with pytest.raises(PholenkValidationError, match="negative_volume"):
        p.get_daily_prices(BBCA, *FULL_RANGE)
    assert build_quality_report(p.normalized_prices(BBCA)).negative_volume_count == 1


# 6. duplicates -------------------------------------------------------------


def test_exact_duplicate_is_collapsed_deterministically(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    write_stock(tmp_path, "BBCA", [row(), row()])
    p = provider(tmp_path)
    assert build_quality_report(p.normalized_prices(BBCA)).duplicate_count == 1
    with caplog.at_level(logging.WARNING):
        [kept] = p.get_daily_prices(BBCA, *FULL_RANGE)
    assert kept.provenance.raw_record_ref.endswith("#line=2")  # lowest source line wins
    assert "collapsed 1 exact duplicate" in caplog.text


def test_conflicting_duplicate_fails_loudly(tmp_path: Path) -> None:
    write_stock(tmp_path, "BBCA", [row(), row(Close="5725.0")])
    with pytest.raises(DuplicateRecordError, match=r"#line=2.*#line=3"):
        provider(tmp_path).get_daily_prices(BBCA, *FULL_RANGE)


# 7. provenance -------------------------------------------------------------


def test_every_record_carries_provenance(tmp_path: Path) -> None:
    path = write_stock(tmp_path, "BBCA", [row(), row(Date="2026-05-26")])
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    prices = provider(tmp_path).get_daily_prices(BBCA, *FULL_RANGE)
    lines = set()
    for price in prices:
        prov = price.provenance
        assert prov.source_id == SOURCE_ID
        assert prov.source_security_id == "BBCA"
        assert prov.retrieved_at == RETRIEVED_AT
        assert prov.raw_record_ref.startswith(f"dataset/stocks/csv/BBCA.csv@sha256:{digest}#line=")
        assert prov.available_at == RETRIEVED_AT and prov.available_at_is_fallback
        assert prov.source_version == f"git:{REVISION}"
        assert "ODbL" in prov.licence_ref
        assert prov.ingestion_run_id == f"{SOURCE_ID}@{REVISION}@20260924T112814Z"
        lines.add(prov.raw_record_ref.rsplit("=", 1)[1])
    assert lines == {"2", "3"}


def test_from_manifest_reads_retrieval_metadata(tmp_path: Path) -> None:
    write_stock(tmp_path, "BBCA", [row()])
    (tmp_path / "manifest.json").write_text(
        json.dumps(
            {"source_id": SOURCE_ID, "revision": REVISION, "retrieved_at": "2026-09-24T11:28:14Z"}
        ),
        encoding="utf-8",
    )
    p = PholenkProvider.from_manifest(tmp_path)
    assert p.retrieved_at == RETRIEVED_AT
    assert p.revision == REVISION


def test_retrieved_at_must_be_timezone_aware(tmp_path: Path) -> None:
    write_stock(tmp_path, "BBCA", [row()])
    with pytest.raises(ValueError, match="timezone-aware"):
        PholenkProvider(tmp_path, retrieved_at=datetime(2026, 9, 24), revision=REVISION)
    wib = timezone(timedelta(hours=7))
    p = PholenkProvider(tmp_path, retrieved_at=RETRIEVED_AT.astimezone(wib), revision=REVISION)
    assert p.retrieved_at == RETRIEVED_AT and p.retrieved_at.tzinfo is UTC


# 8. raw / adjusted flag ----------------------------------------------------


def test_prices_are_marked_raw(tmp_path: Path) -> None:
    write_stock(tmp_path, "BBCA", [row()])
    [price] = provider(tmp_path).get_daily_prices(BBCA, *FULL_RANGE)
    assert price.price_basis is PriceBasis.RAW
    assert price.is_adjusted is False


# 9. deterministic identity --------------------------------------------------


def test_identity_is_deterministic_and_development_only(tmp_path: Path) -> None:
    write_stock(tmp_path, "TLKM", [row(Ticker="TLKM", Name="Telkom Indonesia (Persero) Tbk.")])
    write_stock(
        tmp_path,
        "BBCA",
        [row(Name="Bank Central Asia Tbk."), row(Date="2020-01-02", Name="Old Name")],
    )
    first = [s.source_security_id for s in provider(tmp_path).list_securities()]
    second = [s.source_security_id for s in provider(tmp_path).list_securities()]
    assert first == second == ["dev:pholenk-idx-dataset:BBCA", "dev:pholenk-idx-dataset:TLKM"]
    bbca = provider(tmp_path).list_securities()[0]
    assert bbca.isin is None  # never pretends to be an ISIN
    assert bbca.name == "Bank Central Asia Tbk."  # newest row
    assert source_key(development_security_id("GOTOM")) == "GOTOM"
    with pytest.raises(PholenkFormatError):
        development_security_id("bb ca")
    with pytest.raises(UnknownSecurityError):
        provider(tmp_path).get_daily_prices("dev:pholenk-idx-dataset:ZZZZ", *FULL_RANGE)
    with pytest.raises(UnknownSecurityError):
        source_key("ID1000109507")  # an ISIN is not a development identity


def test_ticker_column_case_mismatch_uses_file_key(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """Observed in the real snapshot: TRUE.csv has Ticker='True'."""
    write_stock(tmp_path, "TRUE", [row(Ticker="True")])
    with caplog.at_level(logging.WARNING):
        [price] = provider(tmp_path).get_daily_prices(development_security_id("TRUE"), *FULL_RANGE)
    assert price.ticker == "TRUE"
    assert "case only" in caplog.text


def test_ticker_column_for_other_security_is_rejected(tmp_path: Path) -> None:
    write_stock(tmp_path, "BBCA", [row(Ticker="BBRI")])
    with pytest.raises(PholenkFormatError, match="does not match file key"):
        provider(tmp_path).get_daily_prices(BBCA, *FULL_RANGE)


# 10. date normalization -----------------------------------------------------


@pytest.mark.parametrize(
    "value", ["2026-05-29", " 2026-05-29 ", "﻿2026-05-29", "2026-05-29T00:00:00"]
)
def test_accepted_date_forms(value: str) -> None:
    assert normalize_trade_date(value) == date(2026, 5, 29)


@pytest.mark.parametrize(
    "value", ["29/05/2026", "2026-5-29", "2026-02-30", "2026-05-29T10:00:00", ""]
)
def test_malformed_dates_are_rejected(value: str) -> None:
    with pytest.raises(PholenkFormatError, match="malformed date"):
        normalize_trade_date(value)


def test_malformed_date_in_file_reports_location(tmp_path: Path) -> None:
    write_stock(tmp_path, "BBCA", [row(Date="29/05/2026")])
    with pytest.raises(PholenkFormatError, match=r"BBCA\.csv@sha256:\w+#line=2"):
        provider(tmp_path).get_daily_prices(BBCA, *FULL_RANGE)


# range, ordering, structure, interface ---------------------------------------


def test_range_filter_and_ascending_order(tmp_path: Path) -> None:
    dates = ["2026-05-29", "2026-05-28", "2026-05-27"]  # source order: newest first
    write_stock(tmp_path, "BBCA", [row(Date=d) for d in dates])
    prices = provider(tmp_path).get_daily_prices(BBCA, date(2026, 5, 28), date(2026, 5, 29))
    assert [p.trade_date for p in prices] == [date(2026, 5, 28), date(2026, 5, 29)]
    with pytest.raises(ValueError, match="after end"):
        provider(tmp_path).get_daily_prices(BBCA, date(2026, 5, 29), date(2026, 5, 28))


def test_unexpected_header_fails(tmp_path: Path) -> None:
    path = write_stock(tmp_path, "BBCA", [row()])
    path.write_text("Date,Close\n2026-05-29,5700\n", encoding="utf-8")
    with pytest.raises(PholenkFormatError, match="unexpected header"):
        provider(tmp_path).get_daily_prices(BBCA, *FULL_RANGE)


def test_non_numeric_price_fails(tmp_path: Path) -> None:
    write_stock(tmp_path, "BBCA", [row(Close="n/a")])
    with pytest.raises(PholenkFormatError, match="Close='n/a' is not a number"):
        provider(tmp_path).get_daily_prices(BBCA, *FULL_RANGE)


def test_provider_satisfies_interface_and_refuses_unprovided_data(tmp_path: Path) -> None:
    write_stock(tmp_path, "BBCA", [row()])
    p = provider(tmp_path)
    assert isinstance(p, MarketDataProvider)
    for call in (
        lambda: p.get_dividends(BBCA, *FULL_RANGE),
        lambda: p.get_corporate_actions(BBCA, *FULL_RANGE),
        lambda: p.get_index_history("COMPOSITE", *FULL_RANGE),
    ):
        with pytest.raises(NotProvidedError):
            call()


def test_quality_report_is_computed_from_input(tmp_path: Path) -> None:
    write_stock(
        tmp_path,
        "BBCA",
        [
            row(Date="2026-05-29"),
            row(Date="2026-05-28", Open="0.0"),
            row(Date="2026-05-27", Open="0.0", High="0.0", Low="0.0", Volume="0", Close="5975.0"),
        ],
    )
    write_stock(tmp_path, "TLKM", [row(Ticker="TLKM", Date="2020-01-02")])
    p = provider(tmp_path)
    report = build_quality_report(
        price for s in p.list_securities() for price in p.normalized_prices(s.source_security_id)
    )
    assert report.rows == 4
    assert report.unique_securities == 2
    assert (report.first_date, report.last_date) == (date(2020, 1, 2), date(2026, 5, 29))
    assert report.duplicate_count == 0
    assert report.missing_open_count == 2
    assert report.missing_open_pct == 50.0
    assert report.zero_volume_rows == 1
    assert report.invalid_ohlc_count == report.negative_volume_count == 0
    assert report.hard_invalid_rows == 0
