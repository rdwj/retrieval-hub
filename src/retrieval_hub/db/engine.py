"""Engine and session helpers for retrieval-hub.

The default database URL points at a local Postgres for development. Production
deployments must always set ``RETRIEVAL_HUB_DB_URL`` explicitly.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

DB_URL_ENV_VAR = "RETRIEVAL_HUB_DB_URL"
DEFAULT_DEV_DB_URL = (
    "postgresql+psycopg://retrievalhub:retrievalhub@127.0.0.1:5432/retrievalhub"
)


def get_default_db_url() -> str:
    """Return the configured database URL or the dev default."""
    return os.environ.get(DB_URL_ENV_VAR, DEFAULT_DEV_DB_URL)


def create_db_engine(url: str | None = None, *, echo: bool = False) -> Engine:
    """Create a SQLAlchemy engine for retrieval-hub."""
    return create_engine(url or get_default_db_url(), echo=echo, future=True)


def make_session_factory(engine: Engine) -> sessionmaker[Session]:
    """Build a session factory bound to the given engine."""
    return sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


@contextmanager
def session_scope(factory: sessionmaker[Session]) -> Iterator[Session]:
    """Provide a transactional session scope.

    Commits on success and rolls back on any exception. Always closes the
    session at the end.
    """
    session = factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
