"""Database engine and session factory.

Purpose
    The one place the application creates its SQLAlchemy engine, so every
    module shares a single connection pool configured from the environment.

Inputs
    ``backend.config.Settings`` (``POSTGRES_*`` variables in ``.env``).

Outputs
    A cached :class:`~sqlalchemy.engine.Engine` via :func:`get_engine`, a
    cached session factory via :func:`get_session_factory`, and
    :func:`ping_database` for health checks.

Assumptions
    PostgreSQL is reachable at the configured host/port -- locally the
    ``postgres`` service in ``docker-compose.yml``.

Limitations
    Synchronous engine only. No ORM models exist yet (Phase 2+). Alembic
    builds its own short-lived engine in ``database/migrations/env.py``.

Example
    >>> from sqlalchemy import text
    >>> from backend.database import get_session_factory
    >>> with get_session_factory()() as session:  # doctest: +SKIP
    ...     session.execute(text("select 1"))
"""

from __future__ import annotations

from functools import lru_cache

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from backend.config import get_settings

# psycopg's own default connect timeout is 130 s, so an unreachable database
# would hang callers for over two minutes before failing.
CONNECT_TIMEOUT_SECONDS = 5


@lru_cache(maxsize=1)
def get_engine() -> Engine:
    """Return the process-wide engine (created lazily, on first use).

    ``pool_pre_ping`` discards connections dropped while idle, e.g. after the
    database container restarts.
    """
    return create_engine(
        get_settings().database_url,
        pool_pre_ping=True,
        connect_args={"connect_timeout": CONNECT_TIMEOUT_SECONDS},
    )


@lru_cache(maxsize=1)
def get_session_factory() -> sessionmaker[Session]:
    """Return the process-wide ``Session`` factory bound to :func:`get_engine`."""
    return sessionmaker(bind=get_engine(), expire_on_commit=False)


def ping_database() -> str:
    """Round-trip ``SELECT version()``; raises on any connection failure."""
    with get_engine().connect() as connection:
        return str(connection.execute(text("select version()")).scalar_one())
