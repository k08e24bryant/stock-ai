"""Alembic migration environment.

The database URL is resolved at runtime from ``backend.config.Settings`` so
that credentials live only in ``.env`` and are never stored in ``alembic.ini``.

Phase 0 note
    ``target_metadata`` points at ``backend.models.metadata``, which is an
    empty ``MetaData`` for now. No schema has been designed yet, so
    autogenerate will correctly produce empty migrations. Tables are added in
    Phase 2 onwards (see PROJECT_PLAN.md).
"""

from __future__ import annotations

from logging.config import fileConfig

from alembic import context
from sqlalchemy import Connection, engine_from_config, pool

from backend.config import get_settings
from backend.models import metadata

config = context.config

if config.config_file_name is not None:
    # Keep application loggers alive when migrations run in-process (e.g. tests):
    # the default would disable every logger created before this call.
    fileConfig(config.config_file_name, disable_existing_loggers=False)

# Alembic's Config is backed by configparser, which treats "%" as interpolation
# syntax. A correctly percent-encoded password (e.g. "%40" for "@") would
# otherwise raise, so escape it.
config.set_main_option("sqlalchemy.url", get_settings().database_url.replace("%", "%%"))

target_metadata = metadata


def run_migrations_offline() -> None:
    """Emit SQL to stdout without connecting to a database."""
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )

    with context.begin_transaction():
        context.run_migrations()


def _run_with(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Connect to the database and run migrations in a transaction.

    A caller may supply its own connection in ``config.attributes["connection"]``
    (Alembic's documented pattern for programmatic use). Tests use this to
    migrate a throwaway database instead of the configured one. The command
    line never sets it, so the CLI always uses the URL from the settings.
    """
    supplied = config.attributes.get("connection")
    if supplied is not None:
        _run_with(supplied)
        return

    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        _run_with(connection)


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
