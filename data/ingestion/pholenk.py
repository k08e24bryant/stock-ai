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
    * ``Volume = 0`` with ``High = Low = 0`` is a zero-volume day whose close
      repeats the previous close. The source does not say whether the security
      was suspended or simply not traded, so the status is
      ``NO_TRADE_OR_SUSPENDED``; high/low become ``None``.

Limitations
    * Identity is **development-only**: ``dev:pholenk-idx-dataset:<KEY>``,
      where KEY is the file name. It is not an ISIN and does not survive
      ticker changes.
    * ``available_at`` is not supplied by the source; the retrieval time is
      used and flagged as a fallback (requirements doc §22).
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
import hashlib
import json
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
from data.validation.daily_prices import (
    Severity,
    build_quality_report,
    find_duplicates,
    is_hard_invalid,
    validate_daily_price,
)

logger = logging.getLogger(__name__)

SOURCE_ID = "pholenk-idx-dataset"
PARSER_VERSION = "pholenk-csv-1"
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


def parse_file(path: Path) -> tuple[PholenkRawRow, ...]:
    """Read one stock file into raw rows, checking the header and row width."""
    with path.open(encoding="utf-8-sig", newline="") as fh:
        reader = csv.reader(fh)
        header = tuple(next(reader, ()))
        if header != EXPECTED_COLUMNS:
            raise PholenkFormatError(f"{path.name}: unexpected header {header!r}")
        rows: list[PholenkRawRow] = []
        for cells in reader:
            if len(cells) != len(header):
                raise PholenkFormatError(
                    f"{path.name}#line={reader.line_num}: {len(cells)} fields, "
                    f"expected {len(header)}"
                )
            rows.append(PholenkRawRow(reader.line_num, dict(zip(header, cells, strict=True))))
    return tuple(rows)


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
    """Map the source's volume/range pattern to an explicit status."""
    if volume > 0:
        return TradingStatus.TRADED
    if volume == 0 and high == 0 and low == 0:
        return TradingStatus.NO_TRADE_OR_SUSPENDED
    return TradingStatus.UNKNOWN


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
        previous_close=_positive_or_none(_decimal(v, "Previous", where)),
        volume_shares=volume,
        value=_decimal(v, "Value", where),
        frequency=_integer(v, "Frequency", where),
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
        ingestion_run_id: str | None = None,
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
        self.ingestion_run_id = ingestion_run_id or (
            f"{SOURCE_ID}@{revision}@{self.retrieved_at:%Y%m%dT%H%M%SZ}"
        )
        self._file_hashes: dict[Path, str] = {}

    @classmethod
    def from_manifest(cls, root: Path) -> PholenkProvider:
        """Build a provider from ``<root>/manifest.json``."""
        manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
        if manifest.get("source_id") != SOURCE_ID:
            raise PholenkFormatError(f"manifest source_id is {manifest.get('source_id')!r}")
        retrieved_at = datetime.fromisoformat(manifest["retrieved_at"].replace("Z", "+00:00"))
        return cls(root, retrieved_at=retrieved_at, revision=manifest["revision"])

    # -- helpers

    def _path(self, key: str) -> Path:
        path = self.stocks_dir / f"{key}.csv"
        if not path.is_file():
            raise UnknownSecurityError(development_security_id(key))
        return path

    def _file_hash(self, path: Path) -> str:
        if path not in self._file_hashes:
            self._file_hashes[path] = hashlib.sha256(path.read_bytes()).hexdigest()
        return self._file_hashes[path]

    def _provenance(self, path: Path, key: str, line: int) -> Provenance:
        rel = path.relative_to(self.root).as_posix()
        return Provenance(
            source_id=SOURCE_ID,
            source_security_id=key,
            retrieved_at=self.retrieved_at,
            ingestion_run_id=self.ingestion_run_id,
            raw_record_ref=f"{rel}@sha256:{self._file_hash(path)}#line={line}",
            licence_ref=self.licence_ref,
            parser_version=PARSER_VERSION,
            available_at=self.retrieved_at,
            available_at_is_fallback=True,
            source_version=f"git:{self.revision}",
        )

    def _keys(self) -> list[str]:
        return sorted(p.stem for p in self.stocks_dir.glob("*.csv"))

    # -- MarketDataProvider

    def list_securities(self) -> list[Security]:
        """One `Security` per stock file; name from the newest row."""
        securities: list[Security] = []
        for key in self._keys():
            path = self._path(key)
            rows = parse_file(path)
            if not rows:
                raise PholenkFormatError(f"{path.name}: no data rows")
            newest = rows[0]
            securities.append(
                Security(
                    source_security_id=development_security_id(key),
                    ticker=key,
                    name=newest.values["Name"].strip() or None,
                    provenance=self._provenance(path, key, newest.line),
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
        raw_rows = parse_file(path)
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
            normalize_row(r, key=key, provenance=self._provenance(path, key, r.line))
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
