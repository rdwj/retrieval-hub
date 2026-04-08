"""Declarative base for retrieval-hub-auth's own ORM models.

This is intentionally separate from ``retrieval_hub.db.base``: the auth
service owns its own tables and its own Alembic history. Sharing a
DeclarativeBase with the core library would couple the two migrations
together, which the platform-component pattern explicitly avoids.
"""

from __future__ import annotations

from typing import Any, cast

from sqlalchemy import JSON, MetaData
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.types import TypeDecorator, TypeEngine

# Consistent naming convention keeps Alembic autogeneration stable and
# matches the one used by the core library (see src/retrieval_hub/db/base.py).
naming_convention: dict[str, str] = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}

metadata = MetaData(naming_convention=naming_convention)


class Base(DeclarativeBase):
    """Declarative base shared by every retrieval-hub-auth ORM model."""

    metadata = metadata


class JSONType(TypeDecorator[Any]):
    """Dialect-aware JSON column.

    Uses ``JSONB`` on PostgreSQL and falls back to ``JSON`` everywhere else.
    The same pattern lives in the core library so migrations stay portable
    across Postgres and the in-memory SQLite we use for tests.
    """

    impl = JSON
    cache_ok = True

    def load_dialect_impl(self, dialect: Any) -> TypeEngine[Any]:
        """Return ``JSONB`` on PostgreSQL; plain ``JSON`` elsewhere."""
        if dialect.name == "postgresql":
            return cast(TypeEngine[Any], dialect.type_descriptor(JSONB()))
        return cast(TypeEngine[Any], dialect.type_descriptor(JSON()))
