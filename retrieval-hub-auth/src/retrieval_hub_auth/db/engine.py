"""Engine and session helpers for retrieval-hub-auth.

These helpers are almost identical to the ones in the core library but are
kept separate so the auth service can be extracted without carrying a
dependency it doesn't otherwise need.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool


def create_db_engine(url: str, *, echo: bool = False) -> Engine:
    """Create a SQLAlchemy engine for retrieval-hub-auth.

    The ``url`` is passed in rather than pulled from the environment so the
    caller (application bootstrap, tests) stays in control of configuration.

    In-memory SQLite deserves special handling: every connection to
    ``sqlite:///:memory:`` gets a *different* private database, so a
    pooled engine will create tables on one connection and then fail to
    find them on the next. Using ``StaticPool`` keeps a single shared
    connection, which is what tests want.
    """
    connect_args: dict[str, object] = {}
    engine_kwargs: dict[str, object] = {"echo": echo, "future": True}
    if url.startswith("sqlite"):
        # Required so multiple threads in TestClient can share the same
        # in-memory database.
        connect_args["check_same_thread"] = False
        if ":memory:" in url or url.endswith(":memory:") or url == "sqlite://":
            engine_kwargs["poolclass"] = StaticPool
    engine_kwargs["connect_args"] = connect_args
    return create_engine(url, **engine_kwargs)


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


def get_session(factory: sessionmaker[Session]) -> Iterator[Session]:
    """FastAPI dependency that yields a session and ensures it's closed.

    Does **not** commit automatically; routes are expected to be explicit
    about their transaction boundaries.
    """
    session = factory()
    try:
        yield session
    finally:
        session.close()
