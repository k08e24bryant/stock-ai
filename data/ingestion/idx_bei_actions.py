"""nichsedge/idx-bei corporate-action events (development source DS-9).

Purpose
    Parse ``data/corporateActions.json`` into raw ``corporate_action_events``
    rows for the record loader (`data.ingestion.records`).

Inputs
    Snapshot ``data/raw/nichsedge-idx-bei/<dir>/`` with ``manifest.json``,
    ``data/corporateActions.json``, ``LICENSE``, and ``README.md``.

Outputs
    `RecordResult`s whose values are the source's own fields: category,
    action label, ticker as published, registration date
    (``TanggalPencatatan``), and both share counts.

Assumptions (measured in docs/data_sources/phase_2c_corporate_actions_design.md §2.4)
    * ``TanggalPencatatan`` is the ex-date for stock splits. For rights, bonus
      shares, and stock dividends it is the listing date of the new shares,
      1–3 weeks after the ex-date.
    * The share counts are stored as published and never used to derive a
      price ratio (they reproduce split ratios only 38 of 51 times).

Limitations
    Incomplete (it misses several splits, e.g. EMTK 2021-01-11). It carries no
    ex-date, ratio, or exercise price. Licence: MIT repository; the data is
    scraped from IDX, so upstream rights are unclear. Development only.

Example
    >>> IdxBeiActionsSource().select_data_files(['LICENSE', DATA_FILE])
    ('data/corporateActions.json',)
"""

from __future__ import annotations

import json
import re
from collections.abc import Sequence
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, cast

from sqlalchemy import Table

from backend.models import CorporateActionEvent
from data.ingestion.records import RecordResult, normalize_ticker
from data.ingestion.snapshot import SnapshotManifest, StructuralError, read_manifest

SOURCE_ID = "nichsedge-idx-bei"
SOURCE_HOMEPAGE = "https://github.com/nichsedge/idx-bei"
PARSER_VERSION = "idx-bei-actions-1"
DATA_FILE = "data/corporateActions.json"
_REQUIRED = (
    "id",
    "KodeEmiten",
    "TanggalPencatatan",
    "JenisTindakan",
    "JumlahSaham",
    "JumlahSahamSetelahTindakan",
)
_MIDNIGHT = re.compile(r"(\d{4}-\d{2}-\d{2})T00:00:00")


def _shares(value: Any) -> Decimal | None:
    if value is None:
        return None
    try:
        shares = Decimal(str(value))
    except InvalidOperation as exc:
        raise ValueError(f"not a number: {value!r}") from exc
    if not shares.is_finite() or shares < 0:
        raise ValueError(f"invalid share count: {value!r}")
    return shares


def _record(category: str, index: int, raw: Any) -> RecordResult:
    ref = f"categories.{category}.data[{index}]"
    if not isinstance(raw, dict):
        return RecordResult(ref, None, None, ("record is not an object",), {"value": raw})
    ticker = raw.get("KodeEmiten")
    match_key = normalize_ticker(ticker) if isinstance(ticker, str) else None
    missing = [k for k in _REQUIRED if k not in raw]
    if missing:
        return RecordResult(ref, None, match_key, (f"missing fields {missing}",), raw)
    try:
        when = _MIDNIGHT.fullmatch(str(raw["TanggalPencatatan"]))
        if when is None:
            raise ValueError(f"unexpected date {raw['TanggalPencatatan']!r}")
        if not isinstance(ticker, str) or not ticker.strip():
            raise ValueError("empty ticker")
        values = {
            "source_record_id": str(raw["id"]),
            "source_category": category,
            "source_action_label": str(raw["JenisTindakan"]),
            "source_ticker": ticker,
            "registration_date": date.fromisoformat(when.group(1)),
            "shares_involved": _shares(raw["JumlahSaham"]),
            "shares_after": _shares(raw["JumlahSahamSetelahTindakan"]),
        }
    except ValueError as exc:
        return RecordResult(ref, None, match_key, (str(exc),), raw)
    return RecordResult(ref, values, match_key, (), raw)


def parse_actions(data: bytes) -> list[RecordResult]:
    """Parse ``corporateActions.json``; structural problems raise `StructuralError`."""
    try:
        doc = json.loads(data.decode("utf-8"), parse_float=Decimal)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise StructuralError(f"{DATA_FILE}: not valid JSON ({exc})") from exc
    if not isinstance(doc, dict) or not isinstance(doc.get("categories"), dict):
        raise StructuralError(f"{DATA_FILE}: expected an object with 'categories'")
    results: list[RecordResult] = []
    for category in sorted(doc["categories"]):
        block = doc["categories"][category]
        if not isinstance(block, dict) or not isinstance(block.get("data"), list):
            raise StructuralError(f"{DATA_FILE}: category {category!r} has no 'data' list")
        if block.get("count") != len(block["data"]):
            raise StructuralError(
                f"{DATA_FILE}: category {category!r} count {block.get('count')} "
                f"!= {len(block['data'])} records"
            )
        results.extend(_record(category, i, raw) for i, raw in enumerate(block["data"]))
    if doc.get("totalRecordsAllTypes") != len(results):
        raise StructuralError(
            f"{DATA_FILE}: totalRecordsAllTypes {doc.get('totalRecordsAllTypes')} "
            f"!= {len(results)} records"
        )
    return results


class IdxBeiActionsSource:
    """`RecordSource` for nichsedge/idx-bei corporate actions."""

    source_id: str = SOURCE_ID
    source_name: str = "nichsedge/idx-bei corporate actions (development source)"
    homepage_url: str | None = SOURCE_HOMEPAGE
    parser_version: str = PARSER_VERSION
    links_securities: bool = True
    provenance_column: str = "record_ref"
    table: Table = cast(Table, CorporateActionEvent.__table__)
    natural_key: tuple[str, ...] = ("source_record_id",)
    observation: tuple[str, ...] = (
        "source_category",
        "source_action_label",
        "source_ticker",
        "registration_date",
        "shares_involved",
        "shares_after",
    )
    date_column: str = "registration_date"

    def read_manifest(self, root: Path) -> SnapshotManifest:
        return read_manifest(
            root,
            source_id=SOURCE_ID,
            default_source_url=SOURCE_HOMEPAGE,
            default_licence="MIT (repository); data scraped from IDX, upstream rights unclear",
        )

    def select_data_files(self, relative_paths: Sequence[str]) -> tuple[str, ...]:
        if DATA_FILE not in relative_paths:
            raise StructuralError(f"data files missing from the snapshot: {[DATA_FILE]}")
        return (DATA_FILE,)

    def parse(self, relative_path: str, data: bytes) -> list[RecordResult]:
        if relative_path != DATA_FILE:
            raise StructuralError(f"not a data file: {relative_path}")
        return parse_actions(data)


__all__ = ["DATA_FILE", "PARSER_VERSION", "SOURCE_ID", "IdxBeiActionsSource", "parse_actions"]
