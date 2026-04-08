"""Tests for the database engine and session helpers."""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import text

from retrieval_hub_auth.db.engine import (
    create_db_engine,
    get_session,
    make_session_factory,
    session_scope,
)


def test_session_scope_commits_on_success(tmp_path: Path) -> None:
    engine = create_db_engine(f"sqlite+pysqlite:///{tmp_path / 'a.sqlite'}")
    factory = make_session_factory(engine)

    with session_scope(factory) as session:
        session.execute(text("CREATE TABLE sanity (id INTEGER)"))
        session.execute(text("INSERT INTO sanity VALUES (1)"))

    with session_scope(factory) as session:
        count = session.execute(text("SELECT COUNT(*) FROM sanity")).scalar_one()
        assert count == 1

    engine.dispose()


def test_session_scope_rolls_back_on_exception(tmp_path: Path) -> None:
    engine = create_db_engine(f"sqlite+pysqlite:///{tmp_path / 'b.sqlite'}")
    factory = make_session_factory(engine)

    with session_scope(factory) as session:
        session.execute(text("CREATE TABLE rollback_me (id INTEGER)"))

    class Boom(Exception):
        pass

    with pytest.raises(Boom):
        with session_scope(factory) as session:
            session.execute(text("INSERT INTO rollback_me VALUES (1)"))
            raise Boom()

    with session_scope(factory) as session:
        count = session.execute(text("SELECT COUNT(*) FROM rollback_me")).scalar_one()
        assert count == 0

    engine.dispose()


def test_get_session_closes_yielded_session(tmp_path: Path) -> None:
    engine = create_db_engine(f"sqlite+pysqlite:///{tmp_path / 'c.sqlite'}")
    factory = make_session_factory(engine)

    gen = get_session(factory)
    session = next(gen)
    assert session is not None
    # Exhaust the generator so the finally: session.close() runs
    with pytest.raises(StopIteration):
        next(gen)

    engine.dispose()
