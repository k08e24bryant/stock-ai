"""Declarative base and shared metadata for all ORM models.

Constraint names are generated deterministically from the naming convention
so that Alembic produces reproducible migrations across machines. CHECK
constraints must be given an explicit ``name``; it becomes
``ck_<table>_<name>``.
"""

from __future__ import annotations

from sqlalchemy import MetaData
from sqlalchemy.orm import DeclarativeBase

NAMING_CONVENTION: dict[str, str] = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}

metadata = MetaData(naming_convention=NAMING_CONVENTION)


class Base(DeclarativeBase):
    """Declarative base shared by all ORM models."""

    metadata = metadata


__all__ = ["NAMING_CONVENTION", "Base", "metadata"]
