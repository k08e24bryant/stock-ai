"""Development market-data provider for the Pholenk/IDX-Dataset snapshot.

Purpose
    Read the public Pholenk/IDX-Dataset daily stock files and return canonical
    `DailyPrice` / `Security` records through the provider-neutral
    `MarketDataProvider` interface. **Development data only**: this source is
    not declared to satisfy production requirements
    (docs/data_sources/market_data_requirements.md §36).

Inputs
    A local snapshot directory (never fetched here) laid out as::

        <root>/manifest.json               retrieval metadata (see from_manifest)
        <root>/dataset/stocks/csv/<KEY>.csv  one file per ticker

    Expected location: ``data/raw/pholenk/IDX-Dataset-<short-revision>/``
    (git-ignored). Source: https://github.com/Pholenk/IDX-Dataset — download
    the repository archive, extract it, and add ``manifest.json``.

Outputs
    Raw rows (`PholenkRawRow`, source strings untouched) and canonical records.

Assumptions (verified against revision 9bb3b26 on 2026-09-24)
    * Files are UTF-8 with a byte-order mark, one header, newest date first.
    * Prices are decimals in IDR; volume is an integer count of **shares**.
    * Prices are **raw** (unadjusted); no adjustment is applied here.
    * ``Open = 0`` means the source did not supply an open. It becomes
      ``open=None`` and is never replaced by another price.
    * ``Volume``, ``Value``, ``Frequency`` are **regular-market** figures.
    * ``Volume = 0`` with ``High = Low = 0`` means no regular-market trade was
      recorded; the close repeats the reference price. The source does not
      say why (suspension, no trading, or non-regular activity only), so the
      status is ``NO_REGULAR_MARKET_TRADE``; open/high/low become ``None``.
    * ``Previous`` is the exchange reference price (``reference_price``), not
      necessarily the prior close.

Limitations
    * Identity is **development-only**: ``dev:pholenk-idx-dataset:<KEY>``,
      where KEY is the file name. It is not an ISIN and does not survive
      ticker changes.
    * Historical availability time is unknown; ``available_at`` stays
      ``None`` (Phase 2B data contract, Decision 3).
    * Dividends, corporate actions, and index history are not provided in
      Phase 2A (`NotProvidedError`).

Example
    >>> development_security_id("BBCA")
    'dev:pholenk-idx-dataset:BBCA'

    Against a local snapshot (not run in tests)::

        provider = PholenkProvider.from_manifest(Path("data/raw/pholenk/IDX-Dataset-9bb3b26"))
        bbca = "dev:pholenk-idx-dataset:BBCA"
        provider.get_daily_prices(bbca, date(2024, 1, 1), date(2024, 12, 31))

    Quality report for a snapshot::

        python -m data.ingestion.pholenk data/raw/pholenk/IDX-Dataset-9bb3b26
"""

from __future__ import annotations

import argparse
import csv
import io
import logging
import re
import sys
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass, fields
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path

from data.ingestion.provider import (
    CorporateAction,
    DailyPrice,
    Dividend,
    IndexLevel,
    NotProvidedError,
    PriceBasis,
    Provenance,
    Security,
    TradingStatus,
)
from data.ingestion.snapshot import (
    SnapshotManifest,
    StructuralError,
    read_bytes,
    sha256_hex,
)
from data.ingestion.snapshot import read_manifest as snapshot_read_manifest
from data.validation.daily_prices import (
    Severity,
    build_quality_report,
    find_duplicates,
    is_hard_invalid,
    validate_daily_price,
)

logger = logging.getLogger(__name__)

SOURCE_ID = "pholenk-idx-dataset"
SOURCE_HOMEPAGE = "https://github.com/Pholenk/IDX-Dataset"
PARSER_VERSION = "pholenk-csv-2"
STOCKS_DIR = Path("dataset") / "stocks" / "csv"
DEV_ID_PREFIX = f"dev:{SOURCE_ID}:"
EXPECTED_COLUMNS: tuple[str, ...] = (
    "Date",
    "Ticker",
    "Name",
    "Remarks",
    "Previous",
    "Open",
    "High",
    "Low",
    "Close",
    "Change",
    "Volume",
    "Value",
    "Frequency",
    "IndexIndividual",
    "Offer",
    "OfferVolume",
    "Bid",
    "BidVolume",
    "ListedShares",
    "TradebleShares",
    "WeightForIndex",
    "ForeignSell",
    "ForeignBuy",
    "NonRegularVolume",
    "NonRegularValue",
    "NonRegularFrequency",
)
FLAG_NON_REGULAR_ACTIVITY = "non_regular_activity_present"
FLAG_UNVERIFIED_TRADING_DATE = "unverified_trading_date"
FLAG_TICKER_COLUMN_MISMATCH = "source_ticker_column_mismatch"
_KEY_RE = re.compile(r"[A-Z0-9]+")
_DATE_RE = re.compile(r"(\d{4}-\d{2}-\d{2})(?:[T ]00:00:00(?:\.0+)?)?")


class PholenkFormatError(ValueError):
    """The snapshot does not have the verified structure; parsing stops."""


class PholenkValidationError(ValueError):
    """Hard-invalid records were found; nothing is returned for that security."""


class DuplicateRecordError(ValueError):
    """Conflicting records share a (security, date) key and cannot be resolved."""


class UnknownSecurityError(KeyError):
    """The requested security is not in this snapshot."""


# ---------------------------------------------------------------- identity


def development_security_id(key: str) -> str:
    """Deterministic development-only identity for a source file key."""
    if not _KEY_RE.fullmatch(key):
        raise PholenkFormatError(f"invalid source key {key!r}")
    return f"{DEV_ID_PREFIX}{key}"


def source_key(security_id: str) -> str:
    """Inverse of `development_security_id`."""
    if not security_id.startswith(DEV_ID_PREFIX):
        raise UnknownSecurityError(security_id)
    key = security_id[len(DEV_ID_PREFIX) :]
    if not _KEY_RE.fullmatch(key):
        raise UnknownSecurityError(security_id)
    return key


# ---------------------------------------------------------------- raw layer


@dataclass(frozen=True, slots=True)
class PholenkRawRow:
    """One CSV row exactly as read; values are the untouched source strings."""

    line: int
    values: Mapping[str, str]


@dataclass(frozen=True, slots=True)
class MalformedRow:
    """A data line that cannot be split into the expected columns."""

    line: int
    cells: tuple[str, ...]
    reason: str


@dataclass(frozen=True, slots=True)
class ParsedStockFile:
    """Rows parsed from one stock file's bytes, plus lines that did not parse."""

    rows: tuple[PholenkRawRow, ...]
    malformed: tuple[MalformedRow, ...]


def parse_bytes(data: bytes, name: str) -> ParsedStockFile:
    """Parse one stock file from exactly these bytes.

    Structural problems (encoding, header) raise `PholenkFormatError`; a data
    line with the wrong number of fields is returned as a `MalformedRow` so a
    caller can quarantine it without discarding the rest of the file.
    """
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise PholenkFormatError(f"{name}: not valid UTF-8 ({exc.reason})") from exc
    reader = csv.reader(io.StringIO(text, newline=""))
    header = tuple(next(reader, ()))
    if header != EXPECTED_COLUMNS:
        raise PholenkFormatError(f"{name}: unexpected header {header!r}")
    rows: list[PholenkRawRow] = []
    malformed: list[MalformedRow] = []
    for cells in reader:
        if len(cells) != len(header):
            reason = f"{len(cells)} fields, expected {len(header)}"
            malformed.append(MalformedRow(reader.line_num, tuple(cells), reason))
            continue
        rows.append(PholenkRawRow(reader.line_num, dict(zip(header, cells, strict=True))))
    return ParsedStockFile(tuple(rows), tuple(malformed))


def parse_file(path: Path) -> tuple[PholenkRawRow, ...]:
    """Strictly parse one stock file: any malformed line raises."""
    parsed = parse_bytes(path.read_bytes(), path.name)
    if parsed.malformed:
        first = parsed.malformed[0]
        raise PholenkFormatError(f"{path.name}#line={first.line}: {first.reason}")
    return parsed.rows


def ticker_case_mismatches(rows: Sequence[PholenkRawRow], key: str) -> tuple[str, ...]:
    """Sorted distinct Ticker cells that differ from the file key only by case."""
    cells = {r.values["Ticker"].strip() for r in rows}
    return tuple(sorted(t for t in cells if t != key and t.upper() == key))


# ---------------------------------------------------------------- normalization


def normalize_trade_date(value: str) -> date:
    """Parse a source date (``YYYY-MM-DD``, optionally with a midnight time)."""
    text = value.strip().lstrip("﻿")
    match = _DATE_RE.fullmatch(text)
    if match is None:
        raise PholenkFormatError(f"malformed date {value!r}")
    try:
        return date.fromisoformat(match.group(1))
    except ValueError as exc:
        raise PholenkFormatError(f"malformed date {value!r}") from exc


def _decimal(values: Mapping[str, str], column: str, where: str) -> Decimal:
    try:
        number = Decimal(values[column].strip())
    except InvalidOperation as exc:
        raise PholenkFormatError(f"{where}: {column}={values[column]!r} is not a number") from exc
    if not number.is_finite():
        raise PholenkFormatError(f"{where}: {column}={values[column]!r} is not finite")
    return number


def _integer(values: Mapping[str, str], column: str, where: str) -> int:
    number = _decimal(values, column, where)
    if number != number.to_integral_value():
        raise PholenkFormatError(f"{where}: {column}={values[column]!r} is not an integer")
    return int(number)


def _positive_or_none(number: Decimal) -> Decimal | None:
    """Source zeros in price fields mean 'not supplied', never a price of 0."""
    return None if number == 0 else number


def classify_trading_status(volume: int, high: Decimal, low: Decimal) -> TradingStatus:
    """Map the source's regular-market volume/range pattern to a status."""
    if volume > 0:
        return TradingStatus.TRADED
    if volume == 0 and high == 0 and low == 0:
        return TradingStatus.NO_REGULAR_MARKET_TRADE
    return TradingStatus.UNKNOWN


def row_quality_flags(non_regular_volume: int, trade_date: date) -> tuple[str, ...]:
    """Documented row flags, sorted and unique (Phase 2B data contract)."""
    flags: set[str] = set()
    if non_regular_volume > 0:
        flags.add(FLAG_NON_REGULAR_ACTIVITY)
    if trade_date.weekday() >= 5:  # no authoritative calendar: weekend check only
        flags.add(FLAG_UNVERIFIED_TRADING_DATE)
    return tuple(sorted(flags))


def normalize_row(raw: PholenkRawRow, *, key: str, provenance: Provenance) -> DailyPrice:
    """Convert one raw row into a canonical record without altering meaning."""
    where = provenance.raw_record_ref
    v = raw.values
    ticker = v["Ticker"].strip()
    if ticker != key and ticker.upper() != key:
        raise PholenkFormatError(f"{where}: Ticker {ticker!r} does not match file key {key!r}")
    try:
        trade_date = normalize_trade_date(v["Date"])
    except PholenkFormatError as exc:
        raise PholenkFormatError(f"{where}: {exc}") from exc
    high = _decimal(v, "High", where)
    low = _decimal(v, "Low", where)
    volume = _integer(v, "Volume", where)
    non_regular_volume = _integer(v, "NonRegularVolume", where)
    return DailyPrice(
        source_security_id=development_security_id(key),
        ticker=key,
        trade_date=trade_date,
        close=_decimal(v, "Close", where),
        price_basis=PriceBasis.RAW,
        trading_status=classify_trading_status(volume, high, low),
        provenance=provenance,
        open=_positive_or_none(_decimal(v, "Open", where)),
        high=_positive_or_none(high),
        low=_positive_or_none(low),
        reference_price=_positive_or_none(_decimal(v, "Previous", where)),
        volume_shares=volume,
        value=_decimal(v, "Value", where),
        frequency=_integer(v, "Frequency", where),
        quality_flags=row_quality_flags(non_regular_volume, trade_date),
    )


# ---------------------------------------------------------------- duplicates


def _content(price: DailyPrice) -> tuple[object, ...]:
    return tuple(getattr(price, f.name) for f in fields(price) if f.name != "provenance")


def _line(price: DailyPrice) -> int:
    return int(price.provenance.raw_record_ref.rsplit("#line=", 1)[1])


def resolve_duplicates(prices: Sequence[DailyPrice]) -> tuple[list[DailyPrice], int]:
    """Collapse exact duplicates deterministically; fail on conflicting ones.

    Exact duplicates (identical content, different source lines) keep the
    record from the lowest source line. Any other duplicate raises
    `DuplicateRecordError`. Returns the kept records and the number dropped.
    """
    groups = find_duplicates(prices)
    if not groups:
        return list(prices), 0
    conflicts = [g for g in groups if len({_content(r) for r in g.records}) > 1]
    if conflicts:
        examples = "; ".join(
            f"{g.source_security_id} {g.trade_date}: "
            + ", ".join(r.provenance.raw_record_ref for r in g.records)
            for g in conflicts[:5]
        )
        raise DuplicateRecordError(
            f"{len(conflicts)} conflicting duplicate key(s), e.g. {examples}"
        )
    drop = {id(r) for g in groups for r in sorted(g.records, key=_line)[1:]}
    kept = [p for p in prices if id(p) not in drop]
    return kept, len(drop)


# ---------------------------------------------------------------- provenance & manifest


def record_provenance(
    *,
    relative_path: str,
    file_sha256: str,
    line: int,
    key: str,
    retrieved_at: datetime,
    revision: str,
    licence_ref: str,
) -> Provenance:
    """Provenance of one source line. `available_at` stays unknown (None)."""
    return Provenance(
        source_id=SOURCE_ID,
        source_security_id=key,
        retrieved_at=retrieved_at,
        raw_record_ref=f"{relative_path}@sha256:{file_sha256}#line={line}",
        licence_ref=licence_ref,
        parser_version=PARSER_VERSION,
        source_version=f"git:{revision}",
    )


def read_manifest(root: Path) -> SnapshotManifest:
    """Read ``<root>/manifest.json`` written when the snapshot was downloaded."""
    try:
        return snapshot_read_manifest(
            root,
            source_id=SOURCE_ID,
            default_source_url=SOURCE_HOMEPAGE,
            default_licence=DEFAULT_LICENCE_REF,
        )
    except StructuralError as exc:
        raise PholenkFormatError(str(exc)) from exc


# ---------------------------------------------------------------- provider

DEFAULT_LICENCE_REF = (
    "ODbL-1.0 (data) https://github.com/Pholenk/IDX-Dataset; underlying data owned by "
    "PT Bursa Efek Indonesia; licence read 2026-09-24"
)


class PholenkProvider:
    """`MarketDataProvider` over a local Pholenk/IDX-Dataset snapshot."""

    def __init__(
        self,
        root: Path,
        *,
        retrieved_at: datetime,
        revision: str,
        licence_ref: str = DEFAULT_LICENCE_REF,
    ) -> None:
        if retrieved_at.tzinfo is None:
            raise ValueError("retrieved_at must be timezone-aware")
        self.root = root
        self.stocks_dir = root / STOCKS_DIR
        if not self.stocks_dir.is_dir():
            raise PholenkFormatError(f"missing directory {self.stocks_dir}")
        self.retrieved_at = retrieved_at.astimezone(UTC)
        self.revision = revision
        self.licence_ref = licence_ref

    @classmethod
    def from_manifest(cls, root: Path) -> PholenkProvider:
        """Build a provider from ``<root>/manifest.json``."""
        manifest = read_manifest(root)
        return cls(root, retrieved_at=manifest.retrieved_at, revision=manifest.revision)

    # -- helpers

    def _path(self, key: str) -> Path:
        path = self.stocks_dir / f"{key}.csv"
        if not path.is_file():
            raise UnknownSecurityError(development_security_id(key))
        return path

    def _read(self, path: Path) -> tuple[ParsedStockFile, str]:
        """Parse a file and hash **the same bytes** (single read)."""
        data = read_bytes(path)
        return parse_bytes(data, path.name), sha256_hex(data)

    def _provenance(self, path: Path, key: str, line: int, file_sha256: str) -> Provenance:
        return record_provenance(
            relative_path=path.relative_to(self.root).as_posix(),
            file_sha256=file_sha256,
            line=line,
            key=key,
            retrieved_at=self.retrieved_at,
            revision=self.revision,
            licence_ref=self.licence_ref,
        )

    def _keys(self) -> list[str]:
        return sorted(p.stem for p in self.stocks_dir.glob("*.csv"))

    # -- MarketDataProvider

    def list_securities(self) -> list[Security]:
        """One `Security` per stock file; name from the newest row."""
        securities: list[Security] = []
        for key in self._keys():
            path = self._path(key)
            parsed, digest = self._read(path)
            if not parsed.rows:
                raise PholenkFormatError(f"{path.name}: no data rows")
            newest = parsed.rows[0]
            securities.append(
                Security(
                    source_security_id=development_security_id(key),
                    ticker=key,
                    name=newest.values["Name"].strip() or None,
                    provenance=self._provenance(path, key, newest.line, digest),
                )
            )
        return securities

    def normalized_prices(self, source_security_id: str) -> list[DailyPrice]:
        """All canonical records for one security, in source order.

        Not validated and not de-duplicated: use `get_daily_prices` for
        consumption and this method for quality reporting.
        """
        key = source_key(source_security_id)
        path = self._path(key)
        parsed, digest = self._read(path)
        if parsed.malformed:
            first = parsed.malformed[0]
            raise PholenkFormatError(f"{path.name}#line={first.line}: {first.reason}")
        raw_rows = parsed.rows
        mismatched = sum(1 for r in raw_rows if r.values["Ticker"].strip() != key)
        if mismatched:
            logger.warning(
                "%s: Ticker column differs from file key %r in %d row(s) (case only); "
                "file key used",
                path.name,
                key,
                mismatched,
            )
        return [
            normalize_row(r, key=key, provenance=self._provenance(path, key, r.line, digest))
            for r in raw_rows
        ]

    def get_daily_prices(self, source_security_id: str, start: date, end: date) -> list[DailyPrice]:
        """Validated records in [start, end], oldest first.

        Raises `PholenkValidationError` on any hard-invalid record and
        `DuplicateRecordError` on conflicting duplicates. Expected source
        conditions (missing open, zero-volume days) are returned, not dropped.
        """
        if start > end:
            raise ValueError(f"start {start} is after end {end}")
        prices = self.normalized_prices(source_security_id)
        checked = [(p, validate_daily_price(p)) for p in prices]
        invalid = [(p, issues) for p, issues in checked if is_hard_invalid(issues)]
        if invalid:
            examples = "; ".join(
                f"{p.provenance.raw_record_ref}: "
                + ",".join(i.code for i in issues if i.severity is Severity.HARD_INVALID)
                for p, issues in invalid[:5]
            )
            raise PholenkValidationError(
                f"{source_security_id}: {len(invalid)} hard-invalid record(s), e.g. {examples}"
            )
        kept, dropped = resolve_duplicates(prices)
        if dropped:
            logger.warning(
                "%s: collapsed %d exact duplicate record(s)", source_security_id, dropped
            )
        selected = [p for p in kept if start <= p.trade_date <= end]
        return sorted(selected, key=lambda p: p.trade_date)

    def get_dividends(self, source_security_id: str, start: date, end: date) -> list[Dividend]:
        raise NotProvidedError("Pholenk provider does not supply dividends (Phase 2A)")

    def get_corporate_actions(
        self, source_security_id: str, start: date, end: date
    ) -> list[CorporateAction]:
        raise NotProvidedError("Pholenk provider does not supply corporate actions (Phase 2A)")

    def get_index_history(self, index_code: str, start: date, end: date) -> list[IndexLevel]:
        raise NotProvidedError("Pholenk index history is not implemented in Phase 2A")


__all__ = [
    "DEV_ID_PREFIX",
    "FLAG_NON_REGULAR_ACTIVITY",
    "FLAG_TICKER_COLUMN_MISMATCH",
    "FLAG_UNVERIFIED_TRADING_DATE",
    "MalformedRow",
    "ParsedStockFile",
    "parse_bytes",
    "read_manifest",
    "record_provenance",
    "row_quality_flags",
    "ticker_case_mismatches",
    "EXPECTED_COLUMNS",
    "PARSER_VERSION",
    "SOURCE_ID",
    "DuplicateRecordError",
    "PholenkFormatError",
    "PholenkProvider",
    "PholenkRawRow",
    "PholenkValidationError",
    "UnknownSecurityError",
    "classify_trading_status",
    "development_security_id",
    "normalize_row",
    "normalize_trade_date",
    "parse_file",
    "resolve_duplicates",
    "source_key",
]


# ---------------------------------------------------------------- report CLI


def main(argv: Sequence[str] | None = None) -> int:
    """Print a quality report for a snapshot: ``python -m data.ingestion.pholenk ROOT``."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else None)
    parser.add_argument("root", type=Path, help="snapshot directory containing manifest.json")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(message)s")
    provider = PholenkProvider.from_manifest(args.root)

    def all_prices() -> Iterator[DailyPrice]:
        for security in provider.list_securities():
            yield from provider.normalized_prices(security.source_security_id)

    report = build_quality_report(all_prices())
    retrieved = f"{provider.retrieved_at:%Y-%m-%dT%H:%M:%SZ}"
    print(f"source: {SOURCE_ID} @ {provider.revision} (retrieved {retrieved})")
    print("\n".join(report.as_lines()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
