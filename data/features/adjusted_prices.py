"""Price-adjusted and total-return series built from raw prices and factors.

Purpose
    The documented price series of CLAUDE.md §17 (design doc §3.2):

    * raw ``close`` (``daily_prices``): display, trading simulation, and
      anything that must be point-in-time at the price level;
    * ``price_return`` / ``adj_close``: price returns, indicators, event
      studies, ML features;
    * ``total_return`` / ``tr_adj_close``: performance, backtest P&L,
      benchmarks.

Inputs
    Raw rows of one security (date, close, reference price), its applied
    factors from ``price_adjustment_factors``, and the reference-price anomaly
    dates of the same build.

Outputs
    `AdjustedBar`s in date order.

Definitions
    * ``price_return(t) = close(t) / reference_price(t) − 1``. On ordinary
      days the reference price is the previous close. On an ex-date it is
      IDX's adjusted reference, so splits and rights never appear as returns.
    * ``total_return(t) = (close(t) + D(t)) / reference_price(t) − 1`` on a
      dividend reinvestment date (requirements doc §24, gross ``D``
      assumed), otherwise equal to ``price_return``.
    * ``adj_close(t) = close(t) × Π price factors with effective date > t``.
      ``tr_adj_close`` also multiplies the dividend factors. Both are
      normalized to the latest date (the last bar equals its raw close).
    * ``reliable`` is False on reference-price anomaly dates (data problems in
      the source). Returns on those dates must not be trusted.
    * A security's **first** row measures its return against that day's
      reference price. For a listing day this is the offering price. On
      2026-09-25, all 15 non-penny daily moves above 35% outside anomaly
      dates were such first rows (IPOs, 2020-01-09 to 2020-03-09, +50% to
      +70%). Exclude first rows where a secondary-market return is required.

Timestamp semantics
    ``price_return`` and ``total_return`` at *t* use only data available at
    the close of *t*. Adjusted **levels** at *t* include factors published
    after *t*: use them for ratios, never as point-in-time price levels.

Example
    >>> from datetime import date
    >>> from decimal import Decimal as D
    >>> bars = adjust(
    ...     [(date(2021, 10, 12), D("36600"), D("36275")),
    ...      (date(2021, 10, 13), D("7525"), D("7325"))],
    ...     price_factors={date(2021, 10, 13): D("7325") / D("36600")},
    ...     dividends={}, anomaly_dates=set())
    >>> [str(b.adj_close.quantize(D("0.01"))) for b in bars]
    ['7325.00', '7525.00']
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, localcontext

from sqlalchemy import Connection, text

from data.features.adjustment_factors import DEFAULT_PRICE_SOURCE, PRECISION, FactorMethod


@dataclass(frozen=True, slots=True)
class AdjustedBar:
    trading_date: date
    close: Decimal
    reference_price: Decimal | None
    price_return: Decimal | None
    total_return: Decimal | None
    dividend: Decimal
    adj_close: Decimal
    tr_adj_close: Decimal
    reliable: bool


def adjust(
    rows: Iterable[tuple[date, Decimal, Decimal | None]],
    *,
    price_factors: dict[date, Decimal],
    dividends: dict[date, tuple[Decimal, Decimal]],
    anomaly_dates: set[date],
) -> list[AdjustedBar]:
    """Pure core. `dividends` maps effective date -> (factor, amount)."""
    ordered = sorted(rows)
    bars: list[AdjustedBar] = []
    with localcontext() as ctx:
        ctx.prec = PRECISION
        price_mult = Decimal(1)
        tr_mult = Decimal(1)
        for trading_date, close, reference in reversed(ordered):
            dividend = dividends.get(trading_date, (Decimal(1), Decimal(0)))[1]
            price_return = close / reference - 1 if reference else None
            total_return = (close + dividend) / reference - 1 if reference else None
            bars.append(
                AdjustedBar(
                    trading_date=trading_date,
                    close=close,
                    reference_price=reference,
                    price_return=price_return,
                    total_return=total_return,
                    dividend=dividend,
                    adj_close=close * price_mult,
                    tr_adj_close=close * tr_mult,
                    reliable=trading_date not in anomaly_dates,
                )
            )
            # Factors effective on this date apply to every earlier close.
            price_mult *= price_factors.get(trading_date, Decimal(1))
            tr_mult *= price_factors.get(trading_date, Decimal(1))
            tr_mult *= dividends.get(trading_date, (Decimal(1), Decimal(0)))[0]
    bars.reverse()
    return bars


def load_adjusted_series(
    conn: Connection,
    security_id: int,
    *,
    price_source_id: str = DEFAULT_PRICE_SOURCE,
    method_version: str = FactorMethod().version,
) -> list[AdjustedBar]:
    """Read one security's raw rows and applied factors, then `adjust` them."""
    params = {"sid": security_id, "src": price_source_id, "m": method_version}
    rows = [
        (d, c, r)
        for d, c, r in conn.execute(
            text(
                "SELECT trading_date, close, reference_price FROM daily_prices "
                "WHERE security_id = :sid AND source_id = :src ORDER BY trading_date"
            ),
            params,
        )
    ]
    price_factors: dict[date, Decimal] = {}
    dividends: dict[date, tuple[Decimal, Decimal]] = {}
    for effective, kind, factor, amount in conn.execute(
        text(
            "SELECT effective_date, factor_kind, factor, dividend_amount "
            "FROM price_adjustment_factors WHERE security_id = :sid AND price_source_id = :src "
            "AND method_version = :m AND status = 'applied'"
        ),
        params,
    ):
        if kind == "price":
            price_factors[effective] = factor
        else:
            dividends[effective] = (factor, amount)
    anomaly_dates = set(
        conn.execute(
            text(
                "SELECT trading_date FROM reference_price_anomaly_dates "
                "WHERE price_source_id = :src AND method_version = :m"
            ),
            params,
        ).scalars()
    )
    return adjust(
        rows, price_factors=price_factors, dividends=dividends, anomaly_dates=anomaly_dates
    )


__all__ = ["AdjustedBar", "adjust", "load_adjusted_series"]
