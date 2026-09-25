"""Shared pytest fixtures and test-environment setup."""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from pathlib import Path

import pytest
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import OperationalError

PROJECT_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="session")
def project_root() -> Path:
    """Absolute path to the repository root."""
    return PROJECT_ROOT


@pytest.fixture(scope="module")
def migrated_database() -> Iterator[Engine]:
    """A throwaway PostgreSQL database, migrated to Alembic ``head``.

    Integration tests that write data use this, never the development
    database: the development database holds the loaded Pholenk snapshot, and
    even rolled-back writes there advance its identity sequences. The
    database is created from the configured server, migrated by the real
    migration (not ``metadata.create_all``), and dropped when the module's
    tests finish. Skips when PostgreSQL is unreachable.
    """
    from alembic import command
    from alembic.config import Config

    from backend.config import get_settings
    from backend.database import get_engine, ping_database

    try:
        ping_database()
    except OperationalError as exc:
        pytest.skip(f"PostgreSQL unreachable ({exc.orig.__class__.__name__})")
    name = f"stockai_test_{uuid.uuid4().hex[:12]}"
    with get_engine().connect() as admin:
        admin.execution_options(isolation_level="AUTOCOMMIT").execute(
            text(f'CREATE DATABASE "{name}"')
        )
    engine = create_engine(make_url(get_settings().database_url).set(database=name))
    try:
        config = Config(str(PROJECT_ROOT / "alembic.ini"))
        with engine.begin() as connection:
            config.attributes["connection"] = connection
            command.upgrade(config, "head")
        yield engine
    finally:
        engine.dispose()
        with get_engine().connect() as admin:
            admin.execution_options(isolation_level="AUTOCOMMIT").execute(
                text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')
            )
