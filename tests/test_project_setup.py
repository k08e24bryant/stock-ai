"""Phase 0 smoke tests.

These prove the development environment and project scaffold are wired up
correctly. They are intentionally cheap and require no database, no network,
and no external data source.
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest

EXPECTED_PACKAGES = [
    "backend",
    "backend.api",
    "backend.models",
    "backend.schemas",
    "backend.services",
    "data",
    "data.ingestion",
    "data.cleaning",
    "data.validation",
    "data.features",
    "ml",
    "ml.sentiment",
    "ml.classification",
    "ml.prediction",
    "ml.training",
    "valuation",
    "event_engine",
    "backtesting",
    "backtesting.engine",
    "backtesting.strategies",
    "backtesting.metrics",
    "workers",
]

EXPECTED_FILES = [
    "pyproject.toml",
    ".gitignore",
    ".env.example",
    "docker-compose.yml",
    "alembic.ini",
    "README.md",
    "CLAUDE.md",
    "CONTEXT.md",
    "PROJECT_PLAN.md",
    "database/migrations/env.py",
]


def test_python_version_is_supported() -> None:
    """The project targets Python 3.13.x (see pyproject requires-python)."""
    assert sys.version_info[:2] == (3, 13)


@pytest.mark.parametrize("module_name", EXPECTED_PACKAGES)
def test_package_is_importable(module_name: str) -> None:
    """Every scaffolded package imports cleanly and is documented."""
    module = importlib.import_module(module_name)
    assert module.__doc__, f"{module_name} is missing a module docstring"


@pytest.mark.parametrize("relative_path", EXPECTED_FILES)
def test_required_file_exists(project_root: Path, relative_path: str) -> None:
    """Foundation files required by Phase 0 are present."""
    assert (project_root / relative_path).is_file()


def test_env_file_is_not_committed(project_root: Path) -> None:
    """`.env` must never be tracked; only `.env.example` is (CLAUDE.md §29)."""
    gitignore = (project_root / ".gitignore").read_text(encoding="utf-8")
    assert ".env" in gitignore
    assert "!.env.example" in gitignore


def test_env_example_documents_every_setting(project_root: Path) -> None:
    """Every Settings field must appear in .env.example, so nothing is hidden."""
    from backend.config import Settings

    example = (project_root / ".env.example").read_text(encoding="utf-8")
    missing = [name for name in Settings.model_fields if name.upper() not in example]
    assert not missing, f"undocumented settings in .env.example: {missing}"


def test_settings_load_with_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    """Settings construct from defaults and build usable connection URLs."""
    from backend.config import AppEnv, Settings

    monkeypatch.delenv("APP_ENV", raising=False)
    settings = Settings(_env_file=None)

    assert settings.app_env is AppEnv.DEVELOPMENT
    assert settings.database_url.startswith("postgresql+psycopg://")
    assert settings.database_url.endswith("@localhost:5432/stockai")
    assert settings.redis_url == "redis://localhost:6379/0"


def test_settings_read_from_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """Environment variables override defaults -- no hardcoded credentials."""
    from backend.config import Settings

    monkeypatch.setenv("POSTGRES_HOST", "db.example.internal")
    monkeypatch.setenv("POSTGRES_PORT", "6543")
    monkeypatch.setenv("POSTGRES_PASSWORD", "s3cret")
    settings = Settings(_env_file=None)

    assert "db.example.internal:6543" in settings.database_url
    assert "s3cret" in settings.database_url


def test_orm_metadata_contains_exactly_the_approved_tables() -> None:
    """Tripwire: adding or removing a table must be a deliberate, reviewed change.

    Phase 0 asserted an empty schema; Phase 2B.2 introduced the approved
    market-data tables (docs/data_sources/phase_2b_schema_design.md); Phase
    2C-2 added corporate actions, dividends, and adjustment factors
    (docs/data_sources/phase_2c_corporate_actions_design.md); Phase 2D added
    index values (docs/data_sources/phase_2d_indices_design.md).
    """
    from backend.models import Base, metadata

    assert Base.metadata is metadata
    assert set(metadata.tables) == {
        "data_sources",
        "source_snapshots",
        "source_files",
        "ingestion_runs",
        "securities",
        "security_source_keys",
        "daily_prices",
        "data_quality_incidents",
        "corporate_action_events",
        "cash_dividends",
        "adjustment_builds",
        "price_adjustment_factors",
        "reference_price_anomaly_dates",
        "index_daily_values",
    }, "Schema changed -- update this assertion and write a reviewed migration."
