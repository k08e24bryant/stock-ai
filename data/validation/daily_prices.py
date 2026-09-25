"""Validation and quality reporting for canonical daily prices.

Purpose
    Classify every `DailyPrice` as valid, carrying an *expected source
    condition* (e.g. missing open, a no-trade day), or *hard invalid*
    (impossible values), and summarise a dataset's quality. Provider-agnostic:
    it only sees canonical records.

Inputs
    `DailyPrice` records (see `data/ingestion/provider.py`).

Outputs
    `ValidationIssue` tuples per record, `DuplicateGroup`s, and a
    `QualityReport` computed from the input (nothing is hard-coded).

Assumptions
    * Rules follow the Phase 2A specification: `high >= low`, `high >= open`
      and `low <= open` when open exists, `high >= close`, `low <= close`,
      `volume >= 0`, and `close > 0`.
    * OHLC relationship rules apply to traded rows only. A no-trade row has no
      high/low and is not rejected merely for that.

Limitations
    Checks each row in isolation; cross-day checks (gaps, jumps not explained
    by corporate actions) are out of scope for Phase 2A.

Example
    >>> from data.validation.daily_prices import build_quality_report
    >>> build_quality_report([]).rows
    0
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date
from enum import StrEnum

from data.ingestion.provider import DailyPrice, TradingStatus


class Severity(StrEnum):
    """How a validation finding must be treated."""

    HARD_INVALID = "hard_invalid"
    EXPECTED_SOURCE_CONDITION = "expected_source_condition"


@dataclass(frozen=True, slots=True)
class ValidationIssue:
    """One finding for one record."""

    code: str
    severity: Severity
    message: str


def _hard(code: str, message: str) -> ValidationIssue:
    return ValidationIssue(code, Severity.HARD_INVALID, message)


def _expected(code: str, message: str) -> ValidationIssue:
    return ValidationIssue(code, Severity.EXPECTED_SOURCE_CONDITION, message)


def validate_daily_price(price: DailyPrice) -> tuple[ValidationIssue, ...]:
    """Return every finding for one record; an empty tuple means clean."""
    issues: list[ValidationIssue] = []
    o, h, low, c = price.open, price.high, price.low, price.close

    if price.volume_shares is not None and price.volume_shares < 0:
        issues.append(_hard("negative_volume", f"volume {price.volume_shares} < 0"))
    for name, value in (("open", o), ("high", h), ("low", low)):
        if value is not None and value <= 0:
            issues.append(_hard(f"non_positive_{name}", f"{name} {value} <= 0"))
    if c <= 0:
        issues.append(_hard("non_positive_close", f"close {c} <= 0"))

    if price.trading_status is TradingStatus.TRADED:
        if h is None or low is None:
            issues.append(_hard("traded_without_range", "traded row has no high/low"))
        else:
            if h < low:
                issues.append(_hard("high_below_low", f"high {h} < low {low}"))
            if h < c:
                issues.append(_hard("high_below_close", f"high {h} < close {c}"))
            if low > c:
                issues.append(_hard("low_above_close", f"low {low} > close {c}"))
            if o is not None and h < o:
                issues.append(_hard("high_below_open", f"high {h} < open {o}"))
            if o is not None and low > o:
                issues.append(_hard("low_above_open", f"low {low} > open {o}"))
    elif price.trading_status is TradingStatus.NO_REGULAR_MARKET_TRADE:
        issues.append(
            _expected(
                "no_regular_market_trade",
                "no regular-market trade recorded; cause not stated by the source",
            )
        )
    elif price.trading_status is TradingStatus.UNKNOWN:
        issues.append(_expected("unclassified_row", "trading status could not be determined"))

    if o is None:
        issues.append(_expected("open_missing", "source did not supply an open price"))
    return tuple(issues)


def is_hard_invalid(issues: Iterable[ValidationIssue]) -> bool:
    """True when any finding is HARD_INVALID."""
    return any(i.severity is Severity.HARD_INVALID for i in issues)


@dataclass(frozen=True, slots=True)
class DuplicateGroup:
    """All records sharing one (security, trading date) key."""

    source_security_id: str
    trade_date: date
    records: tuple[DailyPrice, ...]


def find_duplicates(prices: Iterable[DailyPrice]) -> tuple[DuplicateGroup, ...]:
    """Group records by (security, date); return only keys seen more than once."""
    groups: dict[tuple[str, date], list[DailyPrice]] = defaultdict(list)
    for p in prices:
        groups[(p.source_security_id, p.trade_date)].append(p)
    return tuple(
        DuplicateGroup(sid, d, tuple(rs)) for (sid, d), rs in sorted(groups.items()) if len(rs) > 1
    )


@dataclass(frozen=True, slots=True)
class QualityReport:
    """Dataset-level quality summary, computed from the input records."""

    rows: int
    unique_securities: int
    first_date: date | None
    last_date: date | None
    duplicate_count: int
    missing_open_count: int
    zero_volume_rows: int
    invalid_ohlc_count: int
    negative_volume_count: int
    hard_invalid_rows: int

    @property
    def missing_open_pct(self) -> float:
        return 100.0 * self.missing_open_count / self.rows if self.rows else 0.0

    def as_lines(self) -> list[str]:
        """Human-readable summary lines."""
        return [
            f"rows:                {self.rows}",
            f"unique securities:   {self.unique_securities}",
            f"date range:          {self.first_date} -> {self.last_date}",
            f"duplicate records:   {self.duplicate_count}",
            f"missing open:        {self.missing_open_count} ({self.missing_open_pct:.2f}%)",
            f"zero-volume rows:    {self.zero_volume_rows}",
            f"invalid OHLC rows:   {self.invalid_ohlc_count}",
            f"negative volume:     {self.negative_volume_count}",
            f"hard-invalid rows:   {self.hard_invalid_rows}",
        ]


_OHLC_CODES = frozenset(
    {
        "high_below_low",
        "high_below_close",
        "low_above_close",
        "high_below_open",
        "low_above_open",
        "traded_without_range",
        "non_positive_open",
        "non_positive_high",
        "non_positive_low",
        "non_positive_close",
    }
)


def build_quality_report(prices: Iterable[DailyPrice]) -> QualityReport:
    """Summarise quality in one pass (duplicates need the keys seen so far)."""
    rows = missing_open = zero_volume = invalid_ohlc = negative_volume = hard_rows = 0
    duplicates = 0
    securities: set[str] = set()
    seen: set[tuple[str, date]] = set()
    first: date | None = None
    last: date | None = None
    for p in prices:
        rows += 1
        securities.add(p.source_security_id)
        key = (p.source_security_id, p.trade_date)
        if key in seen:
            duplicates += 1
        seen.add(key)
        first = p.trade_date if first is None else min(first, p.trade_date)
        last = p.trade_date if last is None else max(last, p.trade_date)
        if p.open is None:
            missing_open += 1
        if p.volume_shares == 0:
            zero_volume += 1
        issues = validate_daily_price(p)
        codes = {i.code for i in issues}
        if codes & _OHLC_CODES:
            invalid_ohlc += 1
        if "negative_volume" in codes:
            negative_volume += 1
        if is_hard_invalid(issues):
            hard_rows += 1
    return QualityReport(
        rows=rows,
        unique_securities=len(securities),
        first_date=first,
        last_date=last,
        duplicate_count=duplicates,
        missing_open_count=missing_open,
        zero_volume_rows=zero_volume,
        invalid_ohlc_count=invalid_ohlc,
        negative_volume_count=negative_volume,
        hard_invalid_rows=hard_rows,
    )


__all__ = [
    "DuplicateGroup",
    "QualityReport",
    "Severity",
    "ValidationIssue",
    "build_quality_report",
    "find_duplicates",
    "is_hard_invalid",
    "validate_daily_price",
]
