"""Provider-neutral market-data interface.

Purpose
    Define the minimal contract every market-data source must satisfy, so the
    rest of the system never depends on a specific provider. Development
    (public-dataset) sources and any future licensed production source
    implement the same interface.

Inputs
    None at this layer; implementations decide how to read their source.

Outputs
    Immutable record types (`Security`, `DailyPrice`, `Dividend`,
    `CorporateAction`, `IndexLevel`), each carrying mandatory `Provenance`
    as defined in docs/data_sources/market_data_requirements.md §22.

Assumptions
    * Prices are in the listing currency (IDR for IDX) and use `Decimal` to
      avoid binary floating-point error.
    * Volume is in **shares**, never lots; an implementation must convert.
    * `price_basis` states whether a price is raw or vendor-adjusted. Raw is
      required for production; adjusted values may only be used for
      cross-checking (requirements doc §21, rule 1).
    * Dates are exchange trading dates (WIB for IDX); timestamps are UTC.

Limitations
    Interface only. No provider is implemented here, nothing is fetched, and no
    database schema is implied (Phase 2 implementation is a separate step).

Example
    >>> from datetime import date
    >>> class NullProvider:
    ...     def list_securities(self): return []
    ...     def get_daily_prices(self, source_security_id, start, end): return []
    ...     def get_dividends(self, source_security_id, start, end): return []
    ...     def get_corporate_actions(self, source_security_id, start, end): return []
    ...     def get_index_history(self, index_code, start, end): return []
    >>> isinstance(NullProvider(), MarketDataProvider)
    True
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Protocol, runtime_checkable


class RevisionStatus(StrEnum):
    """Whether a record is the first observation or a correction."""

    ORIGINAL = "original"
    CORRECTION = "correction"
    SUPERSEDED = "superseded"


class PriceBasis(StrEnum):
    """Whether prices are as traded or adjusted by the source."""

    RAW = "raw"
    ADJUSTED = "adjusted"


class TradingStatus(StrEnum):
    """Security-day status (requirement M7).

    Use the most specific status the source actually supports.
    `NO_TRADE_OR_SUSPENDED` exists because many sources show a zero-volume day
    without saying whether the security was suspended or simply not traded;
    that uncertainty must be preserved rather than guessed.
    """

    TRADED = "traded"
    NO_TRADES = "no_trades"
    SUSPENDED = "suspended"
    NO_TRADE_OR_SUSPENDED = "no_trade_or_suspended"
    UNKNOWN = "unknown"


class CorporateActionType(StrEnum):
    """Capital changes relevant to price adjustment (requirement M5)."""

    SPLIT = "split"
    REVERSE_SPLIT = "reverse_split"
    BONUS_SHARES = "bonus_shares"
    STOCK_DIVIDEND = "stock_dividend"
    RIGHTS_ISSUE = "rights_issue"
    OTHER = "other"


@dataclass(frozen=True, slots=True)
class Provenance:
    """Mandatory provenance for every ingested record (requirements doc §22)."""

    source_id: str
    source_security_id: str
    retrieved_at: datetime
    ingestion_run_id: str
    raw_record_ref: str
    licence_ref: str
    parser_version: str
    available_at: datetime
    available_at_is_fallback: bool
    revision_status: RevisionStatus = RevisionStatus.ORIGINAL
    source_timestamp: datetime | None = None
    published_at: datetime | None = None
    source_version: str | None = None


@dataclass(frozen=True, slots=True)
class Security:
    """A listed security as described by one source."""

    source_security_id: str
    ticker: str
    provenance: Provenance
    name: str | None = None
    isin: str | None = None
    listing_date: date | None = None
    delisting_date: date | None = None
    board: str | None = None


@dataclass(frozen=True, slots=True)
class DailyPrice:
    """One security-day of market data. `open` may be unknown in some sources.

    `close` is the source's closing (or reference) price. On a day without
    trades a source may repeat the previous close; `trading_status` tells the
    caller whether `close` reflects trading on that day.
    """

    source_security_id: str
    ticker: str
    trade_date: date
    close: Decimal
    price_basis: PriceBasis
    trading_status: TradingStatus
    provenance: Provenance
    currency: str = "IDR"
    open: Decimal | None = None
    high: Decimal | None = None
    low: Decimal | None = None
    previous_close: Decimal | None = None
    volume_shares: int | None = None
    value: Decimal | None = None
    frequency: int | None = None

    @property
    def is_adjusted(self) -> bool:
        """True when the source adjusted the prices (never the case for raw data)."""
        return self.price_basis is PriceBasis.ADJUSTED


@dataclass(frozen=True, slots=True)
class Dividend:
    """A cash dividend; amounts are gross per share (decision F4)."""

    source_security_id: str
    ex_date: date
    amount_gross: Decimal
    provenance: Provenance
    currency: str = "IDR"
    record_date: date | None = None
    payment_date: date | None = None
    dividend_type: str | None = None


@dataclass(frozen=True, slots=True)
class CorporateAction:
    """A capital change. Fields a source does not supply stay `None`."""

    source_security_id: str
    action_type: CorporateActionType
    provenance: Provenance
    ex_date: date | None = None
    effective_date: date | None = None
    ratio_old: Decimal | None = None
    ratio_new: Decimal | None = None
    subscription_price: Decimal | None = None
    shares_before: int | None = None
    shares_after: int | None = None
    announced_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class IndexLevel:
    """One day of an index (e.g. IHSG / COMPOSITE)."""

    index_code: str
    trade_date: date
    close: Decimal
    provenance: Provenance
    open: Decimal | None = None
    high: Decimal | None = None
    low: Decimal | None = None


class NotProvidedError(NotImplementedError):
    """Raised when a source does not supply a data type.

    Returning an empty result instead would wrongly suggest that, for example,
    a security paid no dividends.
    """


@runtime_checkable
class MarketDataProvider(Protocol):
    """Minimal read-only contract for any market-data source."""

    def list_securities(self) -> Sequence[Security]:
        """All securities the source knows, including delisted ones if available."""
        ...

    def get_daily_prices(
        self, source_security_id: str, start: date, end: date
    ) -> Sequence[DailyPrice]:
        """Daily records for one security within [start, end]."""
        ...

    def get_dividends(self, source_security_id: str, start: date, end: date) -> Sequence[Dividend]:
        """Cash dividends with ex-date within [start, end]."""
        ...

    def get_corporate_actions(
        self, source_security_id: str, start: date, end: date
    ) -> Sequence[CorporateAction]:
        """Capital changes effective within [start, end]."""
        ...

    def get_index_history(self, index_code: str, start: date, end: date) -> Sequence[IndexLevel]:
        """Daily index levels within [start, end]."""
        ...


__all__ = [
    "CorporateAction",
    "CorporateActionType",
    "DailyPrice",
    "Dividend",
    "IndexLevel",
    "MarketDataProvider",
    "NotProvidedError",
    "PriceBasis",
    "Provenance",
    "RevisionStatus",
    "Security",
    "TradingStatus",
]
