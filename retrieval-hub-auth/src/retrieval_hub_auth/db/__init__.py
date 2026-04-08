"""Database layer for retrieval-hub-auth.

This package owns its own declarative base, separate from the core
library's. The auth service lives in the same Postgres instance but in its
own schema (or at least its own tables), so its migrations and models are
independent.
"""

from __future__ import annotations

from retrieval_hub_auth.db.base import Base, metadata
from retrieval_hub_auth.db.engine import (
    create_db_engine,
    get_session,
    make_session_factory,
    session_scope,
)

__all__ = [
    "Base",
    "create_db_engine",
    "get_session",
    "make_session_factory",
    "metadata",
    "session_scope",
]
