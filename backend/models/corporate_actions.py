"""Corporate-action, dividend, and price-adjustment models (Phase 2C).

Purpose
    Tables approved in docs/data_sources/phase_2c_corporate_actions_design.md:

    * ``corporate_action_events``: raw corporate-action records as published
      by an event source (development: nichsedge/idx-bei).
    * ``cash_dividends``: raw cash-dividend records as published by a
      dividend source (development: indonesia-stock-dividends).
    * ``adjustment_builds``: one row per derivation of adjustment factors,
      recording the method, parameters, and inputs.
    * ``price_adjustment_factors``: **derived** factors. Price factors come
      from the exchange reference price (``reference_price / previous close``).
      Cash-dividend factors (``close / (close + dividend)``) follow the
      requirements-doc §24 total-return convention.
    * ``reference_price_anomaly_dates``: **derived** market-wide dates on
      which the reference price disagrees with the previous close for many
      securities at once (a data problem, not corporate actions).

Assumptions
    * ``daily_prices`` is never modified. Adjusted series are computed from
      these factors (``data/features/adjusted_prices.py``).
    * Event and dividend rows keep the source's own values. The link to a
      security is a development heuristic (the ticker text equals a price
      source key), recorded in ``security_match``; it is not an identity.
    * DS-7 does not state whether amounts are gross or net, so it is stored
      as ``unstated``. The total-return method treats it as gross, a
      documented assumption.

Limitations
    Vocabularies are TEXT + CHECK; adding a value needs a migration.

Example
    >>> from backend.models import PriceAdjustmentFactor
    >>> [c.name for c in PriceAdjustmentFactor.__table__.primary_key.columns]
    ['price_source_id', 'method_version', 'security_id', 'effective_date', 'factor_kind']
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Identity,
    Index,
    Integer,
    Numeric,
    Text,
    UniqueConstraint,
    Uuid,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from backend.models.base import Base
from backend.models.market_data import PRICE, RESTRICT

SHARES = Numeric(24, 4)
DIVIDEND_AMOUNT = Numeric(30, 16)

SECURITY_MATCHES = ("ticker_text_match", "unmatched")
AMOUNT_BASES = ("gross", "net", "unstated")
FACTOR_KINDS = ("price", "cash_dividend")
PRICE_FACTOR_CLASSIFICATIONS = (
    "split",
    "reverse_split",
    "rights",
    "bonus",
    "stock_dividend",
    "unclassified",
)
FACTOR_CLASSIFICATIONS = (*PRICE_FACTOR_CLASSIFICATIONS, "cash_dividend")
FACTOR_STATUSES = ("applied", "excluded_market_wide_anomaly")


def _in(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(repr(v) for v in values)})"


def _security_match_consistent() -> CheckConstraint:
    return CheckConstraint(
        "(security_match = 'unmatched') = (security_id IS NULL)",
        name="security_match_consistent",
    )


class CorporateActionEvent(Base):
    """One corporate-action record exactly as the event source published it."""

    __tablename__ = "corporate_action_events"
    __table_args__ = (
        UniqueConstraint("source_id", "source_record_id"),
        CheckConstraint(_in("security_match", SECURITY_MATCHES), name="security_match_vocabulary"),
        _security_match_consistent(),
        CheckConstraint(
            "shares_involved IS NULL OR shares_involved >= 0", name="shares_involved_non_negative"
        ),
        CheckConstraint(
            "shares_after IS NULL OR shares_after >= 0", name="shares_after_non_negative"
        ),
        Index("ix_corporate_action_events_security_id_date", "security_id", "registration_date"),
    )

    event_id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    source_id: Mapped[str] = mapped_column(
        Text, ForeignKey("data_sources.source_id", ondelete=RESTRICT)
    )
    source_record_id: Mapped[str] = mapped_column(Text)
    source_category: Mapped[str] = mapped_column(Text)
    source_action_label: Mapped[str] = mapped_column(Text)
    source_ticker: Mapped[str] = mapped_column(Text)
    security_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("securities.security_id", ondelete=RESTRICT)
    )
    security_match: Mapped[str] = mapped_column(Text)
    registration_date: Mapped[date] = mapped_column(Date)
    shares_involved: Mapped[Decimal | None] = mapped_column(SHARES)
    shares_after: Mapped[Decimal | None] = mapped_column(SHARES)
    file_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("source_files.file_id", ondelete=RESTRICT)
    )
    record_ref: Mapped[str] = mapped_column(Text)
    ingestion_run_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("ingestion_runs.ingestion_run_id", ondelete=RESTRICT)
    )


class CashDividend(Base):
    """One cash-dividend record exactly as the dividend source published it."""

    __tablename__ = "cash_dividends"
    __table_args__ = (
        UniqueConstraint("source_id", "source_ticker", "ex_date"),
        CheckConstraint(_in("security_match", SECURITY_MATCHES), name="security_match_vocabulary"),
        _security_match_consistent(),
        CheckConstraint("amount > 0", name="amount_positive"),
        CheckConstraint(_in("amount_basis", AMOUNT_BASES), name="amount_basis_vocabulary"),
        Index("ix_cash_dividends_security_id_ex_date", "security_id", "ex_date"),
    )

    dividend_id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    source_id: Mapped[str] = mapped_column(
        Text, ForeignKey("data_sources.source_id", ondelete=RESTRICT)
    )
    source_ticker: Mapped[str] = mapped_column(Text)
    ex_date: Mapped[date] = mapped_column(Date)
    security_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("securities.security_id", ondelete=RESTRICT)
    )
    security_match: Mapped[str] = mapped_column(Text)
    amount: Mapped[Decimal] = mapped_column(DIVIDEND_AMOUNT)
    amount_basis: Mapped[str] = mapped_column(Text)
    currency: Mapped[str] = mapped_column(Text, server_default=text("'IDR'"))
    dividend_type: Mapped[str] = mapped_column(Text)
    fiscal_year: Mapped[int | None] = mapped_column(Integer)
    payment_date: Mapped[date | None] = mapped_column(Date)
    file_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("source_files.file_id", ondelete=RESTRICT)
    )
    record_ref: Mapped[str] = mapped_column(Text)
    ingestion_run_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("ingestion_runs.ingestion_run_id", ondelete=RESTRICT)
    )


class AdjustmentBuild(Base):
    """One derivation of adjustment factors: method, parameters, inputs, summary."""

    __tablename__ = "adjustment_builds"

    build_id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    price_source_id: Mapped[str] = mapped_column(
        Text, ForeignKey("data_sources.source_id", ondelete=RESTRICT)
    )
    method_version: Mapped[str] = mapped_column(Text)
    parameters: Mapped[dict[str, Any]] = mapped_column(JSONB)
    inputs: Mapped[dict[str, Any]] = mapped_column(JSONB)
    summary: Mapped[dict[str, Any]] = mapped_column(JSONB)
    built_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class PriceAdjustmentFactor(Base):
    """A derived adjustment factor for one security on one effective date.

    The factor multiplies every close **before** ``effective_date``. For price
    factors, ``effective_date`` is the ex-date. For cash dividends, it is the
    reinvestment date: the ex-date, or the next traded day when the security
    did not trade on the ex-date (requirements doc §24).
    """

    __tablename__ = "price_adjustment_factors"
    __table_args__ = (
        CheckConstraint(_in("factor_kind", FACTOR_KINDS), name="factor_kind_vocabulary"),
        CheckConstraint(
            _in("classification", FACTOR_CLASSIFICATIONS), name="classification_vocabulary"
        ),
        CheckConstraint(_in("status", FACTOR_STATUSES), name="status_vocabulary"),
        CheckConstraint("factor > 0", name="factor_positive"),
        CheckConstraint(
            "(factor_kind = 'cash_dividend') = (classification = 'cash_dividend')",
            name="classification_matches_kind",
        ),
        CheckConstraint(
            "(factor_kind = 'cash_dividend') = (dividend_amount IS NOT NULL)",
            name="dividend_amount_iff_dividend",
        ),
        CheckConstraint(
            "factor_kind <> 'price' OR (prev_close IS NOT NULL AND prev_trading_date IS NOT NULL)",
            name="price_factor_has_previous_row",
        ),
        CheckConstraint("source_line >= 1", name="source_line_positive"),
    )

    price_source_id: Mapped[str] = mapped_column(
        Text, ForeignKey("data_sources.source_id", ondelete=RESTRICT), primary_key=True
    )
    method_version: Mapped[str] = mapped_column(Text, primary_key=True)
    security_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("securities.security_id", ondelete=RESTRICT), primary_key=True
    )
    effective_date: Mapped[date] = mapped_column(Date, primary_key=True)
    factor_kind: Mapped[str] = mapped_column(Text, primary_key=True)
    build_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("adjustment_builds.build_id", ondelete=RESTRICT)
    )
    factor: Mapped[Decimal] = mapped_column(Numeric)
    classification: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text)
    reference_price: Mapped[Decimal] = mapped_column(PRICE)
    close: Mapped[Decimal] = mapped_column(PRICE)
    prev_trading_date: Mapped[date | None] = mapped_column(Date)
    prev_close: Mapped[Decimal | None] = mapped_column(PRICE)
    dividend_amount: Mapped[Decimal | None] = mapped_column(DIVIDEND_AMOUNT)
    source_ex_date: Mapped[date | None] = mapped_column(Date)
    corporate_action_event_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("corporate_action_events.event_id", ondelete=RESTRICT)
    )
    file_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("source_files.file_id", ondelete=RESTRICT)
    )
    source_line: Mapped[int] = mapped_column(Integer)
    prev_file_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("source_files.file_id", ondelete=RESTRICT)
    )
    prev_source_line: Mapped[int | None] = mapped_column(Integer)


class ReferencePriceAnomalyDate(Base):
    """A market-wide date on which reference prices disagree with previous closes."""

    __tablename__ = "reference_price_anomaly_dates"
    __table_args__ = (
        CheckConstraint(
            "mismatched_securities >= 0 AND compared_securities >= mismatched_securities",
            name="counts_consistent",
        ),
    )

    price_source_id: Mapped[str] = mapped_column(
        Text, ForeignKey("data_sources.source_id", ondelete=RESTRICT), primary_key=True
    )
    method_version: Mapped[str] = mapped_column(Text, primary_key=True)
    trading_date: Mapped[date] = mapped_column(Date, primary_key=True)
    build_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("adjustment_builds.build_id", ondelete=RESTRICT)
    )
    mismatched_securities: Mapped[int] = mapped_column(Integer)
    compared_securities: Mapped[int] = mapped_column(Integer)
    shifted_row_matches: Mapped[int] = mapped_column(Integer)


__all__ = [
    "AMOUNT_BASES",
    "FACTOR_CLASSIFICATIONS",
    "FACTOR_KINDS",
    "FACTOR_STATUSES",
    "PRICE_FACTOR_CLASSIFICATIONS",
    "SECURITY_MATCHES",
    "AdjustmentBuild",
    "CashDividend",
    "CorporateActionEvent",
    "PriceAdjustmentFactor",
    "ReferencePriceAnomalyDate",
]
