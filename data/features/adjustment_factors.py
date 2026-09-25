"""Derive price-adjustment factors from raw prices, events, and dividends.

Purpose
    Implement docs/data_sources/phase_2c_corporate_actions_design.md §3 (method
    ``ref-v1``): turn the exchange's reference prices, the event source, and
    the dividend source into ``price_adjustment_factors`` and
    ``reference_price_anomaly_dates``. ``daily_prices`` is only read.

Inputs
    * ``daily_prices`` of one price source (raw; ``reference_price`` is the IDX
      ``Previous`` reference price).
    * ``corporate_action_events`` of an event source (classification only).
    * ``cash_dividends`` of a dividend source (total return only).

Outputs
    A deterministic `FactorBuild` (dry run), written by `write_build`, or
    compared with the stored build by `compare_with_stored`.

Method ``ref-v1`` (definitions)
    * **Price factor** on ex-date *t* of a security:
      ``reference_price(t) / close(t_prev)``, where ``t_prev`` is the
      security's previous row. It exists wherever the two differ; it is IDX's
      own adjustment (splits, reverse splits, rights, bonus shares, stock
      dividends). It multiplies every close **before** *t*.
    * **Market-wide anomaly date**: a date on which at least
      ``market_wide_share`` of the compared securities have
      ``reference_price ≠ previous close``. Measured on 2026-09-25: anomaly
      dates are at 10.2–66%, ordinary dates at most 0.5%, so 5% separates
      them. Factors on these dates are ``excluded_market_wide_anomaly``,
      unless the same day has a split or reverse split in the event source.
    * **Classification** from the event source (never the ratio):
      ``stockSplit`` or ``reverseStock`` registered on the ex-date itself;
      ``hmetd``, ``sahamBonus``, or ``dividenSaham`` registered 0 to
      ``listing_lag_days`` after the ex-date (their date is the listing of the
      new shares). The nearest event wins, ties to the lowest event id.
      Otherwise ``unclassified``, still applied (decision 5).
    * **Cash-dividend factor** (requirements doc §24): the gross dividend
      ``D`` (source amount, assumed gross, decision 3) is reinvested at the
      close of the ex-date, or of the next traded day when the security did
      not trade on the ex-date. The factor is ``close / (close + D)``, which
      makes the adjusted daily return ``(close + D) / reference_price − 1``.
      Dividends dated before a security's first row, or with no traded row
      afterwards, are skipped and counted.

Timestamp semantics
    A factor with effective date *t* is known at the close of *t* (the
    reference price is published for *t*). Back-adjusted **levels** before *t*
    therefore contain later information; **returns** computed from them do
    not.

Limitations
    Development sources only. Rights economics beyond the IDX reference price
    are not modelled (§25). The 18 anomaly dates are flagged, not repaired.

Example
    >>> FactorMethod().version
    'ref-v1'
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import uuid
from collections import Counter, defaultdict
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal, localcontext
from pathlib import Path
from typing import Any

from sqlalchemy import Connection, delete, insert, text

from backend.models import AdjustmentBuild, PriceAdjustmentFactor, ReferencePriceAnomalyDate

PRECISION = 40  # significant digits for factor arithmetic (deterministic)
SAME_DAY_CATEGORIES = {"stockSplit": "split", "reverseStock": "reverse_split"}
LISTING_LAG_CATEGORIES = {
    "hmetd": "rights",
    "sahamBonus": "bonus",
    "dividenSaham": "stock_dividend",
}
DEFAULT_PRICE_SOURCE = "pholenk-idx-dataset"
DEFAULT_EVENT_SOURCE = "nichsedge-idx-bei"
DEFAULT_DIVIDEND_SOURCE = "dimasirginsyh-idx-dividends"


@dataclass(frozen=True, slots=True)
class FactorMethod:
    version: str = "ref-v1"
    market_wide_share: Decimal = Decimal("0.05")
    listing_lag_days: int = 28

    def as_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "market_wide_share": str(self.market_wide_share),
            "listing_lag_days": self.listing_lag_days,
            "same_day_categories": SAME_DAY_CATEGORIES,
            "listing_lag_categories": LISTING_LAG_CATEGORIES,
        }


@dataclass
class FactorBuild:
    """A derivation result; `factors` and `anomalies` are ready to insert."""

    method: FactorMethod
    price_source_id: str
    event_source_id: str | None
    dividend_source_id: str | None
    factors: list[dict[str, Any]] = field(default_factory=list)
    anomalies: list[dict[str, Any]] = field(default_factory=list)
    summary: dict[str, Any] = field(default_factory=dict)
    inputs: dict[str, Any] = field(default_factory=dict)

    def report(self) -> dict[str, Any]:
        """Deterministic description (no build id, no wall-clock time)."""
        digest = hashlib.sha256(
            json.dumps(_canonical(self.factors), sort_keys=True).encode("utf-8")
        ).hexdigest()
        return {
            "method": self.method.as_dict(),
            "price_source_id": self.price_source_id,
            "event_source_id": self.event_source_id,
            "dividend_source_id": self.dividend_source_id,
            "inputs": self.inputs,
            "summary": self.summary,
            "anomaly_dates": _canonical(self.anomalies),
            "factors_sha256": digest,
        }


def _canonical(rows: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    return [{k: str(v) if v is not None else None for k, v in sorted(r.items())} for r in rows]


# ============================================================ derivation (read-only)

_WINDOW = """
    SELECT p.security_id, p.trading_date, p.close, p.reference_price, p.file_id, p.source_line,
           lag(p.trading_date) OVER w AS prev_date, lag(p.close) OVER w AS prev_close,
           lag(p.file_id) OVER w AS prev_file_id, lag(p.source_line) OVER w AS prev_source_line,
           lag(p.close, 2) OVER w AS prev2_close
    FROM daily_prices p WHERE p.source_id = :src
    WINDOW w AS (PARTITION BY p.security_id ORDER BY p.trading_date)
"""


def _date_stats(conn: Connection, price_source_id: str) -> list[tuple[date, int, int, int]]:
    rows = conn.execute(
        text(
            f"SELECT trading_date, "
            "count(*) FILTER (WHERE reference_price <> prev_close), count(*), "
            "count(*) FILTER (WHERE reference_price <> prev_close "
            "AND reference_price = prev2_close) "
            f"FROM ({_WINDOW}) s WHERE prev_close IS NOT NULL AND reference_price IS NOT NULL "
            "GROUP BY trading_date ORDER BY trading_date"
        ),
        {"src": price_source_id},
    ).all()
    return [(d, int(m), int(n), int(sh)) for d, m, n, sh in rows]


def _candidates(conn: Connection, price_source_id: str) -> list[Any]:
    return list(
        conn.execute(
            text(
                f"SELECT * FROM ({_WINDOW}) s WHERE prev_close IS NOT NULL "
                "AND reference_price IS NOT NULL AND reference_price <> prev_close "
                "ORDER BY security_id, trading_date"
            ),
            {"src": price_source_id},
        ).mappings()
    )


def _events(conn: Connection, event_source_id: str | None) -> dict[int, list[Any]]:
    if event_source_id is None:
        return {}
    by_security: dict[int, list[Any]] = defaultdict(list)
    for row in conn.execute(
        text(
            "SELECT event_id, security_id, source_category, registration_date "
            "FROM corporate_action_events WHERE source_id = :src AND security_id IS NOT NULL "
            "AND source_category = ANY(:cats) ORDER BY event_id"
        ),
        {"src": event_source_id, "cats": [*SAME_DAY_CATEGORIES, *LISTING_LAG_CATEGORIES]},
    ).mappings():
        by_security[int(row["security_id"])].append(row)
    return by_security


def _classify(events: list[Any], ex_date: date, lag_days: int) -> tuple[str, int | None]:
    best: tuple[int, int, str] | None = None
    for e in events:
        days = (e["registration_date"] - ex_date).days
        category = e["source_category"]
        if category in SAME_DAY_CATEGORIES and days == 0:
            label = SAME_DAY_CATEGORIES[category]
        elif category in LISTING_LAG_CATEGORIES and 0 <= days <= lag_days:
            label = LISTING_LAG_CATEGORIES[category]
        else:
            continue
        candidate = (abs(days), int(e["event_id"]), label)
        if best is None or candidate < best:
            best = candidate
    if best is None:
        return "unclassified", None
    return best[2], best[1]


def _dividends(conn: Connection, price_source_id: str, dividend_source_id: str) -> list[Any]:
    """Dividends mapped to their reinvestment row (§24), aggregated per ex-date."""
    return list(
        conn.execute(
            text(
                "SELECT d.security_id, d.ex_date, d.amount, r.trading_date, r.close, "
                "r.reference_price, r.file_id, r.source_line, "
                "EXISTS (SELECT 1 FROM daily_prices q WHERE q.security_id = d.security_id "
                "  AND q.source_id = :src AND q.trading_date <= d.ex_date) AS listed_by_ex_date "
                "FROM (SELECT security_id, ex_date, sum(amount) AS amount FROM cash_dividends "
                "      WHERE source_id = :div AND security_id IS NOT NULL GROUP BY 1, 2) d "
                "LEFT JOIN LATERAL (SELECT p.trading_date, p.close, p.reference_price, p.file_id, "
                "  p.source_line FROM daily_prices p WHERE p.security_id = d.security_id "
                "  AND p.source_id = :src AND p.trading_date >= d.ex_date "
                "  AND p.trading_status = 'traded' ORDER BY p.trading_date LIMIT 1) r ON true "
                "ORDER BY d.security_id, d.ex_date"
            ),
            {"src": price_source_id, "div": dividend_source_id},
        ).mappings()
    )


def _snapshots(conn: Connection, source_id: str | None) -> list[str]:
    if source_id is None:
        return []
    return list(
        conn.execute(
            text(
                "SELECT DISTINCT s.snapshot_id FROM source_snapshots s JOIN ingestion_runs r "
                "USING (snapshot_id) WHERE s.source_id = :src AND r.status = 'succeeded' "
                "ORDER BY 1"
            ),
            {"src": source_id},
        ).scalars()
    )


def derive(
    conn: Connection,
    *,
    price_source_id: str = DEFAULT_PRICE_SOURCE,
    event_source_id: str | None = DEFAULT_EVENT_SOURCE,
    dividend_source_id: str | None = DEFAULT_DIVIDEND_SOURCE,
    method: FactorMethod | None = None,
) -> FactorBuild:
    """Compute a factor build. Only reads; safe inside a READ ONLY transaction."""
    method = method or FactorMethod()
    build = FactorBuild(method, price_source_id, event_source_id, dividend_source_id)
    build.inputs = {
        "price_snapshots": _snapshots(conn, price_source_id),
        "event_snapshots": _snapshots(conn, event_source_id),
        "dividend_snapshots": _snapshots(conn, dividend_source_id),
    }
    anomaly_dates: set[date] = set()
    for d, mismatched, compared, shifted in _date_stats(conn, price_source_id):
        if mismatched and Decimal(mismatched) >= method.market_wide_share * compared:
            anomaly_dates.add(d)
            build.anomalies.append(
                {
                    "price_source_id": price_source_id,
                    "method_version": method.version,
                    "trading_date": d,
                    "mismatched_securities": mismatched,
                    "compared_securities": compared,
                    "shifted_row_matches": shifted,
                }
            )
    events = _events(conn, event_source_id)
    counts: Counter[str] = Counter()
    with localcontext() as ctx:
        ctx.prec = PRECISION
        for c in _candidates(conn, price_source_id):
            security_id = int(c["security_id"])
            classification, event_id = _classify(
                events.get(security_id, []), c["trading_date"], method.listing_lag_days
            )
            anomaly = c["trading_date"] in anomaly_dates
            same_day_split = classification in SAME_DAY_CATEGORIES.values()
            status = "excluded_market_wide_anomaly" if anomaly and not same_day_split else "applied"
            counts[f"price.{classification}.{status}"] += 1
            build.factors.append(
                _factor_row(
                    build,
                    security_id,
                    c["trading_date"],
                    "price",
                    factor=c["reference_price"] / c["prev_close"],
                    classification=classification,
                    status=status,
                    reference_price=c["reference_price"],
                    close=c["close"],
                    prev_trading_date=c["prev_date"],
                    prev_close=c["prev_close"],
                    corporate_action_event_id=event_id,
                    file_id=c["file_id"],
                    source_line=c["source_line"],
                    prev_file_id=c["prev_file_id"],
                    prev_source_line=c["prev_source_line"],
                )
            )
        if dividend_source_id is not None:
            _add_dividends(conn, build, counts)
    build.factors.sort(key=lambda r: (r["security_id"], r["effective_date"], r["factor_kind"]))
    build.summary = {
        "anomaly_dates": len(build.anomalies),
        "factor_rows": len(build.factors),
        "securities_with_factors": len({r["security_id"] for r in build.factors}),
        "counts": dict(sorted(counts.items())),
    }
    return build


def _add_dividends(conn: Connection, build: FactorBuild, counts: Counter[str]) -> None:
    assert build.dividend_source_id is not None
    grouped: dict[tuple[int, date], list[Any]] = defaultdict(list)
    for d in _dividends(conn, build.price_source_id, build.dividend_source_id):
        if not d["listed_by_ex_date"]:
            counts["dividend.skipped_before_first_row"] += 1
        elif d["trading_date"] is None:
            counts["dividend.skipped_no_traded_row"] += 1
        else:
            grouped[(int(d["security_id"]), d["trading_date"])].append(d)
    for (security_id, effective), members in sorted(grouped.items()):
        amount = sum((m["amount"] for m in members), Decimal(0))
        first = members[0]
        counts["dividend.applied"] += 1
        counts["dividend.records_applied"] += len(members)
        if effective != first["ex_date"]:
            counts["dividend.postponed_to_next_traded_day"] += 1
        if len(members) > 1:
            counts["dividend.merged_same_effective_date"] += 1
        build.factors.append(
            _factor_row(
                build,
                security_id,
                effective,
                "cash_dividend",
                factor=first["close"] / (first["close"] + amount),
                classification="cash_dividend",
                status="applied",
                reference_price=first["reference_price"],
                close=first["close"],
                dividend_amount=amount,
                source_ex_date=first["ex_date"],
                file_id=first["file_id"],
                source_line=first["source_line"],
            )
        )


def _factor_row(
    build: FactorBuild,
    security_id: int,
    effective_date: date,
    kind: str,
    **values: Any,
) -> dict[str, Any]:
    row: dict[str, Any] = {
        "price_source_id": build.price_source_id,
        "method_version": build.method.version,
        "security_id": security_id,
        "effective_date": effective_date,
        "factor_kind": kind,
        "prev_trading_date": None,
        "prev_close": None,
        "dividend_amount": None,
        "source_ex_date": None,
        "corporate_action_event_id": None,
        "prev_file_id": None,
        "prev_source_line": None,
    }
    row.update(values)
    return row


# ============================================================ write / compare

_KEY = ("security_id", "effective_date", "factor_kind")
_COMPARED = (
    "factor",
    "classification",
    "status",
    "reference_price",
    "close",
    "prev_trading_date",
    "prev_close",
    "dividend_amount",
    "source_ex_date",
    "corporate_action_event_id",
    "file_id",
    "source_line",
    "prev_file_id",
    "prev_source_line",
)


def write_build(conn: Connection, build: FactorBuild) -> uuid.UUID:
    """Replace the stored factors of (price source, method version) with `build`.

    Runs in the caller's transaction; derived rows only. ``daily_prices`` and
    the raw event/dividend tables are never touched.
    """
    lock = int.from_bytes(
        hashlib.sha256(f"stock-ai:derive:{build.price_source_id}".encode()).digest()[:8],
        "big",
        signed=True,
    )
    conn.execute(text("SELECT pg_advisory_xact_lock(:k)"), {"k": lock})
    build_id = uuid.uuid4()
    conn.execute(
        insert(AdjustmentBuild).values(
            build_id=build_id,
            price_source_id=build.price_source_id,
            method_version=build.method.version,
            parameters=build.method.as_dict(),
            inputs={
                **build.inputs,
                "event_source_id": build.event_source_id,
                "dividend_source_id": build.dividend_source_id,
            },
            summary={**build.summary, "factors_sha256": build.report()["factors_sha256"]},
        )
    )
    scope = {"price_source_id": build.price_source_id, "method_version": build.method.version}
    conn.execute(
        delete(PriceAdjustmentFactor).filter_by(**scope),
    )
    conn.execute(delete(ReferencePriceAnomalyDate).filter_by(**scope))
    if build.anomalies:
        conn.execute(
            insert(ReferencePriceAnomalyDate),
            [{**a, "build_id": build_id} for a in build.anomalies],
        )
    for start in range(0, len(build.factors), 1000):
        conn.execute(
            insert(PriceAdjustmentFactor),
            [{**f, "build_id": build_id} for f in build.factors[start : start + 1000]],
        )
    return build_id


def compare_with_stored(conn: Connection, build: FactorBuild) -> dict[str, int]:
    """Differences between `build` and the stored rows of the same scope (read-only)."""
    stored = {
        tuple(r[k] for k in _KEY): r
        for r in conn.execute(
            text(
                "SELECT * FROM price_adjustment_factors "
                "WHERE price_source_id = :src AND method_version = :m"
            ),
            {"src": build.price_source_id, "m": build.method.version},
        ).mappings()
    }
    fresh = {tuple(f[k] for k in _KEY): f for f in build.factors}
    differing = sum(
        1
        for key in stored.keys() & fresh.keys()
        if any(stored[key][c] != fresh[key][c] for c in _COMPARED)
    )
    anomaly_stored = set(
        conn.execute(
            text(
                "SELECT trading_date FROM reference_price_anomaly_dates "
                "WHERE price_source_id = :src AND method_version = :m"
            ),
            {"src": build.price_source_id, "m": build.method.version},
        ).scalars()
    )
    anomaly_fresh = {a["trading_date"] for a in build.anomalies}
    return {
        "factors_missing": len(fresh.keys() - stored.keys()),
        "factors_extra": len(stored.keys() - fresh.keys()),
        "factors_differing": differing,
        "anomaly_dates_differing": len(anomaly_stored ^ anomaly_fresh),
    }


# ============================================================ CLI


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Derive price-adjustment factors (default: read-only dry run)."
    )
    parser.add_argument("--price-source", default=DEFAULT_PRICE_SOURCE)
    parser.add_argument("--event-source", default=DEFAULT_EVENT_SOURCE)
    parser.add_argument("--dividend-source", default=DEFAULT_DIVIDEND_SOURCE)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--execute", action="store_true", help="replace the stored factors (derived tables only)"
    )
    mode.add_argument(
        "--verify", action="store_true", help="read-only: compare stored factors with a fresh build"
    )
    parser.add_argument("--report", type=Path, default=None, help="write the JSON report here")
    args = parser.parse_args(argv)

    from backend.database import get_engine

    sources = {
        "price_source_id": args.price_source,
        "event_source_id": args.event_source,
        "dividend_source_id": args.dividend_source,
    }
    with get_engine().connect() as conn:
        if args.execute:
            with conn.begin():
                build = derive(conn, **sources)
                build_id = write_build(conn, build)
            report: dict[str, Any] = {"mode": "execute", "build_id": str(build_id)}
        else:
            conn.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY"))
            build = derive(conn, **sources)
            report = {"mode": "verify" if args.verify else "dry_run"}
            if args.verify:
                report["differences"] = compare_with_stored(conn, build)
            conn.rollback()
    report.update(build.report())
    rendered = json.dumps(report, sort_keys=True, indent=2, default=str)
    if args.report is None:
        print(rendered)
    else:
        args.report.write_text(rendered + "\n", encoding="utf-8")
    if args.verify and any(report["differences"].values()):
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())


__all__ = [
    "FactorBuild",
    "FactorMethod",
    "compare_with_stored",
    "derive",
    "main",
    "write_build",
]
