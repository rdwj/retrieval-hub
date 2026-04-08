"""Custom SQLAlchemy column types for retrieval-hub.

The catalog stores a fair amount of structured data in JSON columns (recipes,
rewriter metadata, audit detail blobs, etc.). On PostgreSQL we want JSONB so we
get indexing and operator support; on other dialects (notably SQLite, used in
tests) we fall back to plain JSON.
"""

from __future__ import annotations

from typing import Any, cast

from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.types import JSON, TypeDecorator, TypeEngine


class JSONType(TypeDecorator[Any]):
    """Dialect-aware JSON column.

    Uses ``JSONB`` on PostgreSQL and falls back to ``JSON`` everywhere else.
    Application code can treat it as opaque ``dict`` / ``list`` payloads.
    """

    impl = JSON
    cache_ok = True

    def load_dialect_impl(self, dialect: Any) -> TypeEngine[Any]:
        if dialect.name == "postgresql":
            return cast(TypeEngine[Any], dialect.type_descriptor(JSONB()))
        return cast(TypeEngine[Any], dialect.type_descriptor(JSON()))
