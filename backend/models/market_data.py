"""Market-data persistence models (Phase 2B).

Purpose
    SQLAlchemy models for source provenance, security identity, raw daily
    prices, and data-quality incidents, as approved in
    docs/data_sources/phase_2b_schema_design.md and
    docs/data_sources/phase_2b_data_contract.md.

Inputs / Outputs
    Table definitions only; loading is a separate phase.

Assumptions
    * ``daily_prices`` holds **raw, unadjusted** source observations only, so
      it has no ``price_basis`` / ``is_adjusted`` column.
    * Volume, value, and frequency are **regular-market** figures.
    * Historical availability time is unknown and is not stored.
    * All foreign keys are ``ON DELETE RESTRICT``: provenance and market data
      are historical evidence.

Limitations
    * Vocabularies (statuses, flags, incident types) are TEXT + CHECK; adding a
      value needs an explicit migration (Alembic autogenerate does not detect
      CHECK changes).
    * Security identity is development-only (``identity_kind``).

Example
    >>> from backend.models import DailyPrice
    >>> DailyPrice.__table__.primary_key.columns.keys()
    ['security_id', 'trading_date', 'source_id']
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
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from backend.models.base import Base

PRICE = Numeric(20, 4)
MONEY_VALUE = Numeric(24, 4)
SHA256_CHECK = "~ '^[0-9a-f]{64}$'"
RESTRICT = "RESTRICT"

TRADING_STATUSES = ("traded", "no_regular_market_trade", "unknown")
ROW_QUALITY_FLAGS = ("non_regular_activity_present", "unverified_trading_date")
SOURCE_KEY_QUALITY_FLAGS = ("source_ticker_column_mismatch",)
RUN_STATUSES = ("running", "succeeded", "failed")
INCIDENT_TYPES = (
    "conflicting_observation",
    "conflicting_duplicate_in_snapshot",
    "hard_invalid_record",
    "source_ticker_column_mismatch",
    "snapshot_content_mismatch",
)
INCIDENT_STATUSES = ("open", "resolved", "accepted")
INCIDENT_SEVERITIES = ("error", "warning", "info")
IDENTITY_KINDS = ("development",)


def _in(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(repr(v) for v in values)})"


def _flags_within(column: str, values: tuple[str, ...]) -> str:
    """Array holds only documented values and no NULL elements."""
    allowed = ", ".join(repr(v) for v in values)
    return f"{column} <@ ARRAY[{allowed}]::text[] AND array_position({column}, NULL) IS NULL"


def _utc_now() -> Any:
    return func.now()


class DataSource(Base):
    """Logical external source, e.g. ``pholenk-idx-dataset``."""

    __tablename__ = "data_sources"
    __table_args__ = (
        CheckConstraint("source_id ~ '^[a-z0-9][a-z0-9-]*$'", name="source_id_format"),
    )

    source_id: Mapped[str] = mapped_column(Text, primary_key=True)
    source_name: Mapped[str] = mapped_column(Text)
    homepage_url: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=_utc_now())


class SourceSnapshot(Base):
    """One immutable version of an external dataset (the *what*)."""

    __tablename__ = "source_snapshots"
    __table_args__ = (
        UniqueConstraint("source_id", "source_revision", "content_sha256"),
        CheckConstraint(f"content_sha256 {SHA256_CHECK}", name="content_sha256_format"),
        CheckConstraint(
            f"archive_sha256 IS NULL OR archive_sha256 {SHA256_CHECK}",
            name="archive_sha256_format",
        ),
        CheckConstraint(
            "snapshot_id = source_id || ':' || source_revision || ':' || left(content_sha256, 16)",
            name="snapshot_id_derived",
        ),
        CheckConstraint("file_count >= 0", name="file_count_non_negative"),
    )

    snapshot_id: Mapped[str] = mapped_column(Text, primary_key=True)
    source_id: Mapped[str] = mapped_column(
        Text, ForeignKey("data_sources.source_id", ondelete=RESTRICT)
    )
    source_revision: Mapped[str] = mapped_column(Text)
    content_sha256: Mapped[str] = mapped_column(Text)
    archive_sha256: Mapped[str | None] = mapped_column(Text)
    source_url: Mapped[str] = mapped_column(Text)
    retrieved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    licence_reference: Mapped[str] = mapped_column(Text)
    raw_storage_path: Mapped[str] = mapped_column(Text)
    file_count: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=_utc_now())


class SourceFile(Base):
    """Metadata of one raw file in a snapshot; the bytes stay on disk."""

    __tablename__ = "source_files"
    __table_args__ = (
        UniqueConstraint("snapshot_id", "relative_path"),
        CheckConstraint(f"sha256 {SHA256_CHECK}", name="sha256_format"),
        CheckConstraint("row_count >= 0", name="row_count_non_negative"),
    )

    file_id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    snapshot_id: Mapped[str] = mapped_column(
        Text, ForeignKey("source_snapshots.snapshot_id", ondelete=RESTRICT)
    )
    relative_path: Mapped[str] = mapped_column(Text)
    sha256: Mapped[str] = mapped_column(Text)
    row_count: Mapped[int] = mapped_column(Integer)
    source_key: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=_utc_now())


class IngestionRun(Base):
    """One execution of the loader (the *when/how*)."""

    __tablename__ = "ingestion_runs"
    __table_args__ = (
        CheckConstraint(_in("status", RUN_STATUSES), name="status_vocabulary"),
        CheckConstraint(
            "(status = 'running') = (completed_at IS NULL)", name="completion_matches_status"
        ),
        CheckConstraint(
            "completed_at IS NULL OR completed_at >= started_at", name="completed_after_started"
        ),
        CheckConstraint(
            "rows_seen >= 0 AND rows_inserted >= 0 AND rows_unchanged >= 0 "
            "AND rows_rejected >= 0 AND rows_conflicted >= 0",
            name="row_counts_non_negative",
        ),
        Index("ix_ingestion_runs_snapshot_id", "snapshot_id"),
    )

    ingestion_run_id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    snapshot_id: Mapped[str] = mapped_column(
        Text, ForeignKey("source_snapshots.snapshot_id", ondelete=RESTRICT)
    )
    parser_version: Mapped[str] = mapped_column(Text)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(Text)
    rows_seen: Mapped[int] = mapped_column(BigInteger, server_default=text("0"))
    rows_inserted: Mapped[int] = mapped_column(BigInteger, server_default=text("0"))
    rows_unchanged: Mapped[int] = mapped_column(BigInteger, server_default=text("0"))
    rows_rejected: Mapped[int] = mapped_column(BigInteger, server_default=text("0"))
    rows_conflicted: Mapped[int] = mapped_column(BigInteger, server_default=text("0"))
    validation_summary: Mapped[dict[str, Any] | None] = mapped_column(JSONB)


class Security(Base):
    """Internal security identity plus current display metadata."""

    __tablename__ = "securities"
    __table_args__ = (
        CheckConstraint("currency ~ '^[A-Z]{3}$'", name="currency_format"),
        CheckConstraint(_in("identity_kind", IDENTITY_KINDS), name="identity_kind_vocabulary"),
        Index("ix_securities_ticker", "ticker"),
    )

    security_id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    ticker: Mapped[str] = mapped_column(Text)
    name: Mapped[str | None] = mapped_column(Text)
    currency: Mapped[str] = mapped_column(Text, server_default=text("'IDR'"))
    identity_kind: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=_utc_now())


class SecuritySourceKey(Base):
    """Maps a source's natural key to one internal security."""

    __tablename__ = "security_source_keys"
    __table_args__ = (
        CheckConstraint(
            _flags_within("quality_flags", SOURCE_KEY_QUALITY_FLAGS),
            name="quality_flags_vocabulary",
        ),
        Index("ix_security_source_keys_security_id", "security_id"),
    )

    source_id: Mapped[str] = mapped_column(
        Text, ForeignKey("data_sources.source_id", ondelete=RESTRICT), primary_key=True
    )
    source_key: Mapped[str] = mapped_column(Text, primary_key=True)
    security_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("securities.security_id", ondelete=RESTRICT)
    )
    first_seen_snapshot_id: Mapped[str] = mapped_column(
        Text, ForeignKey("source_snapshots.snapshot_id", ondelete=RESTRICT)
    )
    quality_flags: Mapped[list[str]] = mapped_column(
        ARRAY(Text), server_default=text("'{}'::text[]")
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=_utc_now())


class DailyPrice(Base):
    """One raw, unadjusted daily observation of a security by one source."""

    __tablename__ = "daily_prices"
    __table_args__ = (
        CheckConstraint("open IS NULL OR open > 0", name="open_positive"),
        CheckConstraint("high IS NULL OR high > 0", name="high_positive"),
        CheckConstraint("low IS NULL OR low > 0", name="low_positive"),
        CheckConstraint("close > 0", name="close_positive"),
        CheckConstraint(
            "reference_price IS NULL OR reference_price > 0", name="reference_price_positive"
        ),
        CheckConstraint("volume IS NULL OR volume >= 0", name="volume_non_negative"),
        CheckConstraint("value IS NULL OR value >= 0", name="value_non_negative"),
        CheckConstraint("frequency IS NULL OR frequency >= 0", name="frequency_non_negative"),
        CheckConstraint("source_line >= 1", name="source_line_positive"),
        CheckConstraint(_in("trading_status", TRADING_STATUSES), name="trading_status_vocabulary"),
        # Every operand is guarded with IS NOT NULL: a CHECK whose result is NULL
        # passes, so an unguarded "volume > 0" would accept a NULL volume.
        CheckConstraint(
            "trading_status <> 'traded' OR ("
            "volume IS NOT NULL AND volume > 0 "
            "AND high IS NOT NULL AND low IS NOT NULL "
            "AND high >= low AND high >= close AND low <= close "
            "AND (open IS NULL OR (open >= low AND open <= high)))",
            name="traded_shape",
        ),
        CheckConstraint(
            "trading_status <> 'no_regular_market_trade' OR ("
            "volume IS NOT NULL AND volume = 0 "
            "AND open IS NULL AND high IS NULL AND low IS NULL)",
            name="no_regular_trade_shape",
        ),
        CheckConstraint(
            _flags_within("quality_flags", ROW_QUALITY_FLAGS), name="quality_flags_vocabulary"
        ),
        Index("ix_daily_prices_trading_date", "trading_date"),
    )

    security_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("securities.security_id", ondelete=RESTRICT), primary_key=True
    )
    trading_date: Mapped[date] = mapped_column(Date, primary_key=True)
    source_id: Mapped[str] = mapped_column(
        Text, ForeignKey("data_sources.source_id", ondelete=RESTRICT), primary_key=True
    )
    open: Mapped[Decimal | None] = mapped_column(PRICE)
    high: Mapped[Decimal | None] = mapped_column(PRICE)
    low: Mapped[Decimal | None] = mapped_column(PRICE)
    close: Mapped[Decimal] = mapped_column(PRICE)
    reference_price: Mapped[Decimal | None] = mapped_column(PRICE)
    volume: Mapped[int | None] = mapped_column(BigInteger)
    value: Mapped[Decimal | None] = mapped_column(MONEY_VALUE)
    frequency: Mapped[int | None] = mapped_column(BigInteger)
    trading_status: Mapped[str] = mapped_column(Text)
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


class DataQualityIncident(Base):
    """A data-quality event: conflict, rejected record, or source anomaly."""

    __tablename__ = "data_quality_incidents"
    __table_args__ = (
        CheckConstraint(_in("incident_type", INCIDENT_TYPES), name="incident_type_vocabulary"),
        CheckConstraint(_in("status", INCIDENT_STATUSES), name="status_vocabulary"),
        CheckConstraint(_in("severity", INCIDENT_SEVERITIES), name="severity_vocabulary"),
        CheckConstraint("source_line IS NULL OR source_line >= 1", name="source_line_positive"),
        Index("ix_data_quality_incidents_ingestion_run_id", "ingestion_run_id"),
        Index("ix_data_quality_incidents_security_id_trading_date", "security_id", "trading_date"),
    )

    incident_id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    ingestion_run_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("ingestion_runs.ingestion_run_id", ondelete=RESTRICT)
    )
    incident_type: Mapped[str] = mapped_column(Text)
    severity: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, server_default=text("'open'"))
    source_id: Mapped[str | None] = mapped_column(
        Text, ForeignKey("data_sources.source_id", ondelete=RESTRICT)
    )
    security_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("securities.security_id", ondelete=RESTRICT)
    )
    trading_date: Mapped[date | None] = mapped_column(Date)
    file_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("source_files.file_id", ondelete=RESTRICT)
    )
    source_line: Mapped[int | None] = mapped_column(Integer)
    details: Mapped[dict[str, Any]] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=_utc_now())


__all__ = [
    "INCIDENT_TYPES",
    "ROW_QUALITY_FLAGS",
    "SOURCE_KEY_QUALITY_FLAGS",
    "TRADING_STATUSES",
    "DailyPrice",
    "DataQualityIncident",
    "DataSource",
    "IngestionRun",
    "Security",
    "SecuritySourceKey",
    "SourceFile",
    "SourceSnapshot",
]
