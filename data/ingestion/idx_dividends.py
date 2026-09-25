"""indonesia-stock-dividends cash dividends (development source DS-7).

Purpose
    Parse ``all_dividends.json`` into raw ``cash_dividends`` rows for the
    record loader (`data.ingestion.records`).

Inputs
    Snapshot ``data/raw/dimasirginsyh-idx-dividends/<dir>/`` with
    ``manifest.json``, ``all_dividends.json``, and ``README.md``.

Outputs
    `RecordResult`s holding the source's own fields: ticker as published
    (``AADI.JK``), ex-date, amount per share (exact decimal), dividend type,
    fiscal year, and payment date (often missing).

Assumptions
    * The source does not say whether amounts are gross or net, so they are
      stored with ``amount_basis = 'unstated'``. The total-return method
      (requirements doc §24, Phase 2C decision 3) treats them as gross; that
      is a documented assumption, not a fact.
    * Amounts are IDR per share on the share basis of the ex-date.
    * ``(ticker, ex_date)`` is unique in the source (measured 2026-09-25) and
      is the natural key.
    * A malformed ``payment_date`` (6 records on 2026-09-25, e.g.
      ``'2025-06-9'``) is stored as NULL and reported as a
      ``malformed_optional_field`` incident; the dividend itself is kept.

Limitations
    No licence (LICENSE UNCLEAR); upstream mitbal/daguerreo-data, collected
    from IDX. No record date. ``payment_date`` is missing in about 45% of
    records. Development only.

Example
    >>> IdxDividendsSource().natural_key
    ('source_ticker', 'ex_date')
"""

from __future__ import annotations

import json
import re
from collections.abc import Sequence
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any, cast

from sqlalchemy import Table

from backend.models import CashDividend
from data.ingestion.records import RecordResult, normalize_ticker
from data.ingestion.snapshot import SnapshotManifest, StructuralError, read_manifest

SOURCE_ID = "dimasirginsyh-idx-dividends"
SOURCE_HOMEPAGE = "https://github.com/dimasirginsyh/indonesia-stock-dividends"
PARSER_VERSION = "idx-dividends-1"
DATA_FILE = "all_dividends.json"
_AMOUNT = re.compile(r"\d+(\.\d+)?")
_ISO_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")
_YEAR = re.compile(r"\d{4}")


def _iso_date(value: Any, field: str) -> date:
    if not isinstance(value, str) or not _ISO_DATE.fullmatch(value):
        raise ValueError(f"{field}: unexpected date {value!r}")
    return date.fromisoformat(value)


def _optional_date(value: Any, field: str) -> tuple[date | None, tuple[dict[str, Any], ...]]:
    """An optional date: None when absent; None plus an issue when malformed.

    A malformed value (e.g. ``'2025-06-9'``) is **not** repaired: it is stored as
    unknown and reported, because guessing would invent data.
    """
    if value in (None, ""):
        return None, ()
    try:
        return _iso_date(value, field), ()
    except ValueError as exc:
        return None, ({"field": field, "raw": value, "reason": str(exc)},)


def _record(ticker: str, index: int, raw: Any) -> RecordResult:
    ref = f"{ticker}[{index}]"
    match_key = normalize_ticker(ticker.removesuffix(".JK"))
    if not isinstance(raw, dict):
        return RecordResult(ref, None, match_key, ("record is not an object",), {"value": raw})
    try:
        amount = str(raw.get("dividend", ""))
        if not _AMOUNT.fullmatch(amount) or Decimal(amount) <= 0:
            raise ValueError(f"dividend: not a positive amount {raw.get('dividend')!r}")
        year = str(raw.get("fiscal_year", ""))
        if not _YEAR.fullmatch(year):
            raise ValueError(f"fiscal_year: unexpected value {raw.get('fiscal_year')!r}")
        dividend_type = raw.get("dividend_type")
        if not isinstance(dividend_type, str) or not dividend_type:
            raise ValueError(f"dividend_type: unexpected value {dividend_type!r}")
        payment, issues = _optional_date(raw.get("payment_date"), "payment_date")
        values = {
            "source_ticker": ticker,
            "ex_date": _iso_date(raw.get("ex_date"), "ex_date"),
            "amount": Decimal(amount),
            "amount_basis": "unstated",
            "currency": "IDR",
            "dividend_type": dividend_type,
            "fiscal_year": int(year),
            "payment_date": payment,
        }
    except ValueError as exc:
        return RecordResult(ref, None, match_key, (str(exc),), raw)
    return RecordResult(ref, values, match_key, (), raw, issues)


def parse_dividends(data: bytes) -> list[RecordResult]:
    """Parse ``all_dividends.json``; structural problems raise `StructuralError`."""
    try:
        doc = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise StructuralError(f"{DATA_FILE}: not valid JSON ({exc})") from exc
    if not isinstance(doc, dict):
        raise StructuralError(f"{DATA_FILE}: expected an object keyed by ticker")
    results: list[RecordResult] = []
    for ticker in sorted(doc):
        records = doc[ticker]
        if not isinstance(records, list):
            raise StructuralError(f"{DATA_FILE}: {ticker!r} is not a list")
        results.extend(_record(ticker, i, raw) for i, raw in enumerate(records))
    return results


class IdxDividendsSource:
    """`RecordSource` for indonesia-stock-dividends cash dividends."""

    source_id: str = SOURCE_ID
    source_name: str = "indonesia-stock-dividends cash dividends (development source)"
    homepage_url: str | None = SOURCE_HOMEPAGE
    parser_version: str = PARSER_VERSION
    links_securities: bool = True
    provenance_column: str = "record_ref"
    table: Table = cast(Table, CashDividend.__table__)
    natural_key: tuple[str, ...] = ("source_ticker", "ex_date")
    observation: tuple[str, ...] = (
        "amount",
        "amount_basis",
        "currency",
        "dividend_type",
        "fiscal_year",
        "payment_date",
    )
    date_column: str = "ex_date"

    def read_manifest(self, root: Path) -> SnapshotManifest:
        return read_manifest(
            root,
            source_id=SOURCE_ID,
            default_source_url=SOURCE_HOMEPAGE,
            default_licence="none (LICENSE UNCLEAR); upstream mitbal/daguerreo-data",
        )

    def select_data_files(self, relative_paths: Sequence[str]) -> tuple[str, ...]:
        if DATA_FILE not in relative_paths:
            raise StructuralError(f"data files missing from the snapshot: {[DATA_FILE]}")
        return (DATA_FILE,)

    def parse(self, relative_path: str, data: bytes) -> list[RecordResult]:
        if relative_path != DATA_FILE:
            raise StructuralError(f"not a data file: {relative_path}")
        return parse_dividends(data)


__all__ = ["DATA_FILE", "PARSER_VERSION", "SOURCE_ID", "IdxDividendsSource", "parse_dividends"]
