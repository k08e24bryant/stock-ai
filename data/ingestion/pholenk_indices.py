"""Pholenk/IDX-Dataset index files (Phase 2D development source).

Purpose
    Parse ``dataset/indices/csv/<CODE>.csv`` of an already-registered Pholenk
    snapshot into raw ``index_daily_values`` rows. The record loader
    (`data.ingestion.records`) handles identity, runs, idempotency, conflicts,
    and provenance.

Inputs
    The Pholenk snapshot directory (the same one the daily prices come from).

Outputs
    `RecordResult`s whose ``record_ref`` is the source line number.

Assumptions (measured on revision ``9bb3b26``, 2026-09-25)
    * 56 files share one 11-column header (UTF-8 with BOM): ``Date, Previous,
      Highest, Lowest, Close, Constituent, Change, Volume, Value, Frequency,
      Capitalization``. There is no open.
    * ``Change`` equals ``Close − Previous`` on every row. It is checked here
      and not stored.
    * The index code is the file key (for example ``COMPOSITE`` for IHSG).
    * Weekend dates (only 2021-05-22) are kept and flagged
      ``unverified_trading_date``, as for stocks.

Limitations
    The preview file ``dataset/preview/indices/csv/ABX.csv`` is not loaded
    (the preview directory is never data). Development source only.

Example
    >>> PholenkIndexSource().select_data_files(
    ...     ["dataset/indices/csv/COMPOSITE.csv", "dataset/stocks/csv/BBCA.csv"])
    ('dataset/indices/csv/COMPOSITE.csv',)
"""

from __future__ import annotations

import csv
import io
import re
from collections.abc import Sequence
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, cast

from sqlalchemy import Table

from backend.models import IndexDailyValue
from data.ingestion.pholenk import SOURCE_HOMEPAGE, SOURCE_ID, PholenkFormatError, read_manifest
from data.ingestion.records import RecordResult
from data.ingestion.snapshot import SnapshotManifest, StructuralError

PARSER_VERSION = "pholenk-index-csv-1"
INDEX_DIR = "dataset/indices/csv/"
HEADER = (
    "Date",
    "Previous",
    "Highest",
    "Lowest",
    "Close",
    "Constituent",
    "Change",
    "Volume",
    "Value",
    "Frequency",
    "Capitalization",
)
_INDEX_FILE = re.compile(r"dataset/indices/csv/([A-Za-z0-9-]+)\.csv")
_ISO_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")
CHANGE_TOLERANCE = Decimal("0.001")  # source values have at most 3 decimals


def _number(value: str, column: str) -> Decimal:
    try:
        number = Decimal(value)
    except InvalidOperation as exc:
        raise ValueError(f"{column}={value!r} is not a number") from exc
    if not number.is_finite():
        raise ValueError(f"{column}={value!r} is not finite")
    return number


def _integer(value: str, column: str) -> int:
    number = _number(value, column)
    if number != number.to_integral_value():
        raise ValueError(f"{column}={value!r} is not an integer")
    return int(number)


def _row(code: str, line: int, cells: list[str]) -> RecordResult:
    raw: dict[str, Any] = dict(zip(HEADER, cells, strict=False))
    if len(cells) != len(HEADER):
        reason = f"{len(cells)} fields, expected {len(HEADER)}"
        return RecordResult(str(line), None, None, (reason,), raw)
    try:
        if not _ISO_DATE.fullmatch(cells[0]):
            raise ValueError(f"Date={cells[0]!r} is not YYYY-MM-DD")
        trading_date = date.fromisoformat(cells[0])
        previous, high, low, close = (_number(cells[i], HEADER[i]) for i in range(1, 5))
        change = _number(cells[6], "Change")
        problems = []
        if min(previous, high, low, close) <= 0:
            problems.append("non_positive_value")
        if high < low:
            problems.append("high_below_low")
        if not low <= close <= high:
            problems.append("close_outside_high_low")
        if abs((close - previous) - change) > CHANGE_TOLERANCE:
            problems.append("change_differs_from_close_minus_previous")
        if problems:
            return RecordResult(str(line), None, None, tuple(problems), raw)
        values = {
            "index_code": code,
            "trading_date": trading_date,
            "previous": previous,
            "high": high,
            "low": low,
            "close": close,
            "constituents": _integer(cells[5], "Constituent"),
            "volume": _integer(cells[7], "Volume"),
            "value": _number(cells[8], "Value"),
            "frequency": _integer(cells[9], "Frequency"),
            "capitalization": _number(cells[10], "Capitalization"),
            "quality_flags": ["unverified_trading_date"] if trading_date.weekday() >= 5 else [],
        }
    except ValueError as exc:
        return RecordResult(str(line), None, None, (str(exc),), raw)
    return RecordResult(str(line), values, None, (), raw)


def parse_index_file(relative_path: str, data: bytes) -> list[RecordResult]:
    """Parse one index CSV; header or encoding problems raise `StructuralError`."""
    match = _INDEX_FILE.fullmatch(relative_path)
    if match is None:
        raise StructuralError(f"not an index file: {relative_path}")
    try:
        content = data.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise StructuralError(f"{relative_path}: not valid UTF-8 ({exc.reason})") from exc
    reader = csv.reader(io.StringIO(content, newline=""))
    header = tuple(next(reader, ()))
    if header != HEADER:
        raise StructuralError(f"{relative_path}: unexpected header {header!r}")
    return [_row(match.group(1), reader.line_num, cells) for cells in reader]


class PholenkIndexSource:
    """`RecordSource` for the index files of a Pholenk snapshot."""

    source_id: str = SOURCE_ID
    source_name: str = "Pholenk IDX-Dataset (development source)"
    homepage_url: str | None = SOURCE_HOMEPAGE
    parser_version: str = PARSER_VERSION
    table: Table = cast(Table, IndexDailyValue.__table__)
    natural_key: tuple[str, ...] = ("index_code", "trading_date")
    observation: tuple[str, ...] = (
        "previous",
        "high",
        "low",
        "close",
        "constituents",
        "volume",
        "value",
        "frequency",
        "capitalization",
        "quality_flags",
    )
    date_column: str = "trading_date"
    links_securities: bool = False
    provenance_column: str = "source_line"

    def read_manifest(self, root: Path) -> SnapshotManifest:
        try:
            return read_manifest(root)
        except PholenkFormatError as exc:
            raise StructuralError(str(exc)) from exc

    def select_data_files(self, relative_paths: Sequence[str]) -> tuple[str, ...]:
        in_dir = [p for p in relative_paths if p.startswith(INDEX_DIR)]
        unexpected = [p for p in in_dir if not _INDEX_FILE.fullmatch(p)]
        if unexpected:
            raise StructuralError(f"unexpected files in the index directory: {unexpected}")
        if not in_dir:
            raise StructuralError(f"no index files under {INDEX_DIR}")
        return tuple(sorted(in_dir))

    def parse(self, relative_path: str, data: bytes) -> list[RecordResult]:
        return parse_index_file(relative_path, data)


__all__ = ["HEADER", "PARSER_VERSION", "PholenkIndexSource", "parse_index_file"]
