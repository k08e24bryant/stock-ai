"""Daily index series (benchmarks) with explicit reliability.

Purpose
    Benchmark returns for relative strength, market regime, event studies,
    and backtest comparison (CLAUDE.md §6, §11, §12, §20). The source is
    ``index_daily_values`` (raw, e.g. ``COMPOSITE`` = IHSG).

Definitions
    * ``index_return(t) = close(t) / previous(t) − 1``, where ``previous`` is
      the exchange's previous value. Index levels have no corporate actions
      to adjust.
    * ``reliable`` is False when the row is flagged ``unverified_trading_date``,
      or when ``previous(t)`` differs from the stored close of the prior row
      (a continuity break). On 2026-09-25 this marks only 2021-05-22 and
      2021-05-24.

Timestamp semantics
    ``index_return(t)`` uses only values published for day *t*.

Example
    >>> from datetime import date
    >>> from decimal import Decimal as D
    >>> bars = index_returns([(date(2024, 1, 2), D("100"), D("100"), []),
    ...                       (date(2024, 1, 3), D("101"), D("100"), [])])
    >>> str(bars[1].index_return), bars[1].reliable
    ('0.01', True)
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from sqlalchemy import Connection, text

DEFAULT_SOURCE = "pholenk-idx-dataset"
BENCHMARK = "COMPOSITE"  # IHSG


@dataclass(frozen=True, slots=True)
class IndexBar:
    trading_date: date
    close: Decimal
    previous: Decimal
    index_return: Decimal
    reliable: bool


def index_returns(rows: Iterable[tuple[date, Decimal, Decimal, list[str]]]) -> list[IndexBar]:
    """Pure core over (date, close, previous, quality_flags) rows."""
    bars: list[IndexBar] = []
    prior_close: Decimal | None = None
    for trading_date, close, previous, flags in sorted(rows, key=lambda r: r[0]):
        continuous = prior_close is None or previous == prior_close
        bars.append(
            IndexBar(
                trading_date=trading_date,
                close=close,
                previous=previous,
                index_return=close / previous - 1,
                reliable=continuous and "unverified_trading_date" not in flags,
            )
        )
        prior_close = close
    return bars


def load_index_series(
    conn: Connection, index_code: str = BENCHMARK, *, source_id: str = DEFAULT_SOURCE
) -> list[IndexBar]:
    rows = conn.execute(
        text(
            "SELECT trading_date, close, previous, quality_flags FROM index_daily_values "
            "WHERE source_id = :src AND index_code = :code ORDER BY trading_date"
        ),
        {"src": source_id, "code": index_code},
    ).all()
    return index_returns((d, c, p, list(f)) for d, c, p, f in rows)


__all__ = ["BENCHMARK", "IndexBar", "index_returns", "load_index_series"]
