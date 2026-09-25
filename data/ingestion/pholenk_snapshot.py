"""Pholenk/IDX-Dataset adapter for the generic snapshot loader.

Purpose
    Tell the provider-agnostic loader (`data.ingestion.loader`) how to read a
    Pholenk snapshot: file roles, structural rules, per-file inspection, and
    per-row normalization. Normalization itself lives in
    `data.ingestion.pholenk` so the provider and the loader share one mapping.

Inputs
    Snapshot-relative paths and the exact bytes read for each file.

Outputs
    `FileInspection` (pass 1) and `RowResult`s (pass 2).

Assumptions
    * Only ``dataset/stocks/csv/<KEY>.csv`` files are securities. Index,
      preview, and documentation files are inventoried for provenance but never
      produce securities or prices.
    * A stock file name must be ``[A-Z0-9]+.csv``; anything else in the stock
      directory is a structural error.

Limitations
    Development source only (requirements doc §36).

Example
    >>> PholenkSnapshotSource().classify("dataset/indices/csv/COMPOSITE.csv")
    <FileRole.INDEX: 'index'>
"""

from __future__ import annotations

import csv
import io
import re
from collections.abc import Iterator
from datetime import date
from pathlib import Path

from data.ingestion.loader import FileInspection, RowResult
from data.ingestion.pholenk import (
    DEFAULT_LICENCE_REF,
    PARSER_VERSION,
    SOURCE_ID,
    PholenkFormatError,
    normalize_row,
    normalize_trade_date,
    parse_bytes,
    read_manifest,
    record_provenance,
    ticker_case_mismatches,
)
from data.ingestion.snapshot import FileRole, SnapshotManifest, StructuralError

STOCK_PREFIX = "dataset/stocks/"
_STOCK_PATH = re.compile(r"dataset/stocks/csv/([A-Z0-9]+)\.csv")


class PholenkSnapshotSource:
    """`SnapshotSource` implementation for Pholenk/IDX-Dataset snapshots."""

    source_id: str = SOURCE_ID
    source_name: str = "Pholenk IDX-Dataset (development source)"
    homepage_url: str | None = "https://github.com/Pholenk/IDX-Dataset"
    parser_version: str = PARSER_VERSION

    def read_manifest(self, root: Path) -> SnapshotManifest:
        try:
            return read_manifest(root)
        except PholenkFormatError as exc:
            raise StructuralError(str(exc)) from exc

    def classify(self, relative_path: str) -> FileRole:
        if relative_path.startswith(STOCK_PREFIX):
            if not _STOCK_PATH.fullmatch(relative_path):
                raise StructuralError(f"unexpected file in stock directory: {relative_path}")
            return FileRole.STOCK
        if relative_path.startswith("dataset/indices/"):
            return FileRole.INDEX
        if relative_path.startswith("dataset/preview/"):
            return FileRole.PREVIEW
        return FileRole.OTHER

    def inspect(self, relative_path: str, data: bytes, role: FileRole) -> FileInspection:
        if role is not FileRole.STOCK:
            return FileInspection(row_count=_csv_data_rows(relative_path, data))
        key = _stock_key(relative_path)
        try:
            parsed = parse_bytes(data, relative_path)
        except PholenkFormatError as exc:
            raise StructuralError(str(exc)) from exc
        newest_date: date | None = None
        newest_name: str | None = None
        for row in parsed.rows:
            try:
                row_date = normalize_trade_date(row.values["Date"])
            except PholenkFormatError:
                continue
            if newest_date is None or row_date > newest_date:
                newest_date, newest_name = row_date, row.values["Name"].strip() or None
        return FileInspection(
            row_count=len(parsed.rows) + len(parsed.malformed),
            source_key=key,
            newest_name=newest_name,
            newest_date=newest_date,
            ticker_mismatch_values=ticker_case_mismatches(parsed.rows, key),
        )

    def iter_rows(
        self,
        relative_path: str,
        data: bytes,
        file_sha256: str,
        manifest: SnapshotManifest,
    ) -> Iterator[RowResult]:
        key = _stock_key(relative_path)
        try:
            parsed = parse_bytes(data, relative_path)
        except PholenkFormatError as exc:
            raise StructuralError(str(exc)) from exc
        for bad in parsed.malformed:
            yield RowResult(line=bad.line, price=None, cells=bad.cells, reasons=(bad.reason,))
        for raw in parsed.rows:
            provenance = record_provenance(
                relative_path=relative_path,
                file_sha256=file_sha256,
                line=raw.line,
                key=key,
                retrieved_at=manifest.retrieved_at,
                revision=manifest.revision,
                licence_ref=manifest.licence_reference or DEFAULT_LICENCE_REF,
            )
            try:
                price = normalize_row(raw, key=key, provenance=provenance)
            except PholenkFormatError as exc:
                cells = tuple(raw.values.values())
                yield RowResult(line=raw.line, price=None, cells=cells, reasons=(str(exc),))
                continue
            yield RowResult(line=raw.line, price=price, cells=(), reasons=())


def _stock_key(relative_path: str) -> str:
    match = _STOCK_PATH.fullmatch(relative_path)
    if match is None:
        raise StructuralError(f"not a stock file path: {relative_path}")
    return match.group(1)


def _csv_data_rows(relative_path: str, data: bytes) -> int:
    """Data rows of a non-stock CSV (header excluded); 0 for other files."""
    if not relative_path.endswith(".csv"):
        return 0
    text = data.decode("utf-8-sig", errors="replace")
    return max(sum(1 for _ in csv.reader(io.StringIO(text, newline=""))) - 1, 0)


__all__ = ["PholenkSnapshotSource"]
