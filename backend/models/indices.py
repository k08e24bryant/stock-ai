"""Market-index models (Phase 2D).

Purpose
    ``index_daily_values``: raw daily index values exactly as the source
    publishes them (development: the 56 index files of the Pholenk snapshot).
    See docs/data_sources/phase_2d_indices_design.md.

Assumptions
    * An index is identified by ``(source_id, index_code)``, where the code is
      the file key (``COMPOSITE`` = IHSG). No separate index entity exists yet;
      one is added when a second index source needs mapping.
    * The source has no open. ``previous`` is the exchange's previous value;
      the change (``close − previous``) is not stored because it is derivable,
      and it was verified equal for every row on 2026-09-25.
    * ``quality_flags`` reuses the daily-price vocabulary; only
      ``unverified_trading_date`` (weekend dates) applies.

Example
    >>> from backend.models import IndexDailyValue
    >>> [c.name for c in IndexDailyValue.__table__.primary_key.columns]
    ['source_id', 'index_code', 'trading_date']
"""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Date,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    Text,
    Uuid,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column

from backend.models.base import Base
from backend.models.market_data import PRICE, RESTRICT

INDEX_QUALITY_FLAGS = ("unverified_trading_date",)
AMOUNT = Numeric(24, 4)


class IndexDailyValue(Base):
    """One index on one trading day, as published (raw, never adjusted)."""

    __tablename__ = "index_daily_values"
    __table_args__ = (
        CheckConstraint("index_code ~ '^[A-Za-z0-9-]+$'", name="index_code_format"),
        CheckConstraint(
            "previous > 0 AND high > 0 AND low > 0 AND close > 0", name="values_positive"
        ),
        CheckConstraint(
            "high >= low AND close >= low AND close <= high", name="high_low_close_shape"
        ),
        CheckConstraint(
            "(constituents IS NULL OR constituents >= 0) AND (volume IS NULL OR volume >= 0) "
            "AND (value IS NULL OR value >= 0) AND (frequency IS NULL OR frequency >= 0) "
            "AND (capitalization IS NULL OR capitalization >= 0)",
            name="counts_non_negative",
        ),
        CheckConstraint(
            "quality_flags <@ ARRAY['unverified_trading_date']::text[] "
            "AND array_position(quality_flags, NULL) IS NULL",
            name="quality_flags_vocabulary",
        ),
        CheckConstraint("source_line >= 1", name="source_line_positive"),
        Index("ix_index_daily_values_trading_date", "trading_date"),
    )

    source_id: Mapped[str] = mapped_column(
        Text, ForeignKey("data_sources.source_id", ondelete=RESTRICT), primary_key=True
    )
    index_code: Mapped[str] = mapped_column(Text, primary_key=True)
    trading_date: Mapped[date] = mapped_column(Date, primary_key=True)
    previous: Mapped[Decimal] = mapped_column(PRICE)
    high: Mapped[Decimal] = mapped_column(PRICE)
    low: Mapped[Decimal] = mapped_column(PRICE)
    close: Mapped[Decimal] = mapped_column(PRICE)
    constituents: Mapped[int | None] = mapped_column(Integer)
    volume: Mapped[int | None] = mapped_column(BigInteger)
    value: Mapped[Decimal | None] = mapped_column(AMOUNT)
    frequency: Mapped[int | None] = mapped_column(BigInteger)
    capitalization: Mapped[Decimal | None] = mapped_column(AMOUNT)
    quality_flags: Mapped[list[str]] = mapped_column(
        ARRAY(Text), server_default=text("'{}'::text[]")
    )
    file_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("source_files.file_id", ondelete=RESTRICT)
    )
    source_line: Mapped[int] = mapped_column(Integer)
    ingestion_run_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("ingestion_runs.ingestion_run_id", ondelete=RESTRICT)
    )


# Observed trading calendar (a view created by migration; not an ORM table).
OBSERVED_TRADING_DAYS_VIEW = """
CREATE VIEW observed_trading_days AS
SELECT d.source_id,
       d.trading_date,
       coalesce(s.stock_rows, 0) AS stock_rows,
       coalesce(i.index_rows, 0) AS index_rows,
       coalesce(s.stock_rows, 0) > 0 AS in_stock_data,
       coalesce(i.index_rows, 0) > 0 AS in_index_data,
       extract(isodow FROM d.trading_date) >= 6 AS is_weekend
FROM (SELECT source_id, trading_date FROM daily_prices
      UNION SELECT source_id, trading_date FROM index_daily_values) d
LEFT JOIN (SELECT source_id, trading_date, count(*) AS stock_rows
           FROM daily_prices GROUP BY 1, 2) s USING (source_id, trading_date)
LEFT JOIN (SELECT source_id, trading_date, count(*) AS index_rows
           FROM index_daily_values GROUP BY 1, 2) i USING (source_id, trading_date)
"""


__all__ = ["INDEX_QUALITY_FLAGS", "OBSERVED_TRADING_DAYS_VIEW", "IndexDailyValue"]
