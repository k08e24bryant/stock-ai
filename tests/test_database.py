"""Phase 1 database and service connectivity tests.

Unit tests (always run) check that connection URLs survive credentials with
URL-reserved characters. Tests marked ``integration`` talk to the live
PostgreSQL and Redis from ``docker-compose.yml`` and are skipped -- with the
reason reported by ``-ra`` -- when those services are not reachable.
"""

from __future__ import annotations

import socket
from collections.abc import Iterator
from pathlib import Path

import pytest
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import OperationalError

from backend.config import Settings, get_settings
from backend.database import get_engine, get_session_factory, ping_database

HOSTILE_PASSWORD = "p@ss/w:rd%40#?"


def test_database_url_escapes_reserved_characters_in_password() -> None:
    """A password containing @ / : % # ? must not leak into host or database."""
    settings = Settings(
        _env_file=None,
        postgres_host="localhost",
        postgres_port=5432,
        postgres_db="stockai",
        postgres_password=HOSTILE_PASSWORD,
    )
    url = make_url(settings.database_url)

    assert url.password == HOSTILE_PASSWORD
    assert url.host == "localhost"
    assert url.port == 5432
    assert url.database == "stockai"


def test_escaped_database_url_is_accepted_by_alembic_config() -> None:
    """env.py's %-escaping lets Alembic's configparser round-trip the URL."""
    url = Settings(_env_file=None, postgres_password=HOSTILE_PASSWORD).database_url
    config = Config()
    config.set_main_option("sqlalchemy.url", url.replace("%", "%%"))

    assert config.get_main_option("sqlalchemy.url") == url


# --------------------------------------------------------------------------
# Integration: live services
# --------------------------------------------------------------------------


@pytest.fixture(scope="module")
def live_database() -> Iterator[None]:
    """Skip unless the configured PostgreSQL accepts connections."""
    try:
        ping_database()
    except OperationalError as exc:
        pytest.skip(
            f"PostgreSQL unreachable ({exc.orig.__class__.__name__}); run `docker compose up -d`"
        )
    yield
    get_engine().dispose()


def _redis_ping(host: str, port: int) -> bytes:
    """Send a raw RESP PING. Avoids a `redis` dependency before Phase workers."""
    with socket.create_connection((host, port), timeout=3) as sock:
        sock.sendall(b"*1\r\n$4\r\nPING\r\n")
        return sock.recv(64)


@pytest.mark.integration
@pytest.mark.usefixtures("live_database")
def test_postgres_accepts_connections_with_configured_credentials() -> None:
    settings = get_settings()
    with get_session_factory()() as session:
        user, database = session.execute(text("select current_user, current_database()")).one()

    assert user == settings.postgres_user
    assert database == settings.postgres_db
    assert ping_database().startswith("PostgreSQL 17")


@pytest.mark.integration
@pytest.mark.usefixtures("live_database")
def test_alembic_upgrade_head_succeeds(project_root: Path) -> None:
    """`alembic upgrade head` runs cleanly against the configured database."""
    from alembic import command

    command.upgrade(Config(str(project_root / "alembic.ini")), "head")


@pytest.mark.integration
def test_redis_responds_to_ping() -> None:
    settings = get_settings()
    try:
        reply = _redis_ping(settings.redis_host, settings.redis_port)
    except OSError as exc:
        pytest.skip(f"Redis unreachable ({exc.__class__.__name__}); run `docker compose up -d`")

    assert reply == b"+PONG\r\n"
