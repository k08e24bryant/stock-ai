"""Application configuration.

Purpose
    Single source of truth for runtime configuration. Every value is read from
    the environment (or a local ``.env`` file), never hardcoded -- CLAUDE.md §29.

Inputs
    Environment variables documented in ``.env.example``.

Outputs
    A cached :class:`Settings` instance via :func:`get_settings`.

Assumptions
    ``.env`` lives at the repository root and is git-ignored. Missing values
    fall back to the local development defaults declared below, except for
    secrets, which have deliberately weak placeholder defaults so that a
    production misconfiguration is obvious rather than silent.

Limitations
    Phase 0 scope: application, PostgreSQL, and Redis settings only. No data
    provider credentials exist yet because no provider has been selected.

Example
    >>> from backend.config import get_settings
    >>> get_settings().app_env
    'development'
"""

from __future__ import annotations

from enum import StrEnum
from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT: Path = Path(__file__).resolve().parents[1]


class AppEnv(StrEnum):
    """Deployment environment the process believes it is running in."""

    DEVELOPMENT = "development"
    TEST = "test"
    PRODUCTION = "production"


class Settings(BaseSettings):
    """Runtime settings loaded from the environment."""

    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
        frozen=True,
    )

    # --- Application ---
    app_env: AppEnv = AppEnv.DEVELOPMENT
    log_level: str = "INFO"

    # --- PostgreSQL ---
    postgres_host: str = "localhost"
    postgres_port: int = Field(default=5432, ge=1, le=65535)
    postgres_db: str = "stockai"
    postgres_user: str = "stockai"
    postgres_password: str = "change_me_locally"

    # --- Redis ---
    redis_host: str = "localhost"
    redis_port: int = Field(default=6379, ge=1, le=65535)
    redis_db: int = Field(default=0, ge=0)

    @property
    def database_url(self) -> str:
        """SQLAlchemy/psycopg connection URL for the primary database."""
        return (
            f"postgresql+psycopg://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    @property
    def redis_url(self) -> str:
        """Connection URL for Redis."""
        return f"redis://{self.redis_host}:{self.redis_port}/{self.redis_db}"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the process-wide settings instance (loaded once)."""
    return Settings()
