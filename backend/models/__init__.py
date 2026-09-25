"""SQLAlchemy ORM models.

Purpose
    Declarative base, shared ``MetaData``, and every persisted entity.
    Importing this package registers all models on ``metadata``, which is the
    target Alembic autogenerate compares against.

Contents
    * ``base`` — ``Base``, ``metadata``, and the constraint naming convention.
    * ``market_data`` — Phase 2B market-data tables (see
      docs/data_sources/phase_2b_schema_design.md).
    * ``corporate_actions`` — Phase 2C corporate actions, dividends, and
      derived price-adjustment factors (see
      docs/data_sources/phase_2c_corporate_actions_design.md).

Naming convention
    Constraint names are generated deterministically so that Alembic produces
    reproducible migrations across machines.
"""

from __future__ import annotations

from backend.models.base import NAMING_CONVENTION, Base, metadata
from backend.models.corporate_actions import (
    AdjustmentBuild,
    CashDividend,
    CorporateActionEvent,
    PriceAdjustmentFactor,
    ReferencePriceAnomalyDate,
)
from backend.models.market_data import (
    DailyPrice,
    DataQualityIncident,
    DataSource,
    IngestionRun,
    Security,
    SecuritySourceKey,
    SourceFile,
    SourceSnapshot,
)

__all__ = [
    "NAMING_CONVENTION",
    "AdjustmentBuild",
    "Base",
    "CashDividend",
    "CorporateActionEvent",
    "DailyPrice",
    "DataQualityIncident",
    "DataSource",
    "IngestionRun",
    "PriceAdjustmentFactor",
    "ReferencePriceAnomalyDate",
    "Security",
    "SecuritySourceKey",
    "SourceFile",
    "SourceSnapshot",
    "metadata",
]
