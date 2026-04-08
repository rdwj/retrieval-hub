"""Tests for the ``RecipeVersion`` model."""

from __future__ import annotations

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from retrieval_hub.models import RecipeVersion
from tests.conftest import make_recipe_version, make_source


def test_recipe_version_round_trip(session: Session) -> None:
    """A recipe version persists with its full JSON content intact."""
    src = make_source(session)
    rv = make_recipe_version(
        session,
        src,
        version_number=1,
        content={
            "parser": {"kind": "docling", "options": {"ocr": True}},
            "chunker": {"kind": "semantic", "chunk_size_tokens": 512},
            "embedding": {"model": "nomic-embed-text-v1.5", "dimension": 768},
            "backend": {"kind": "pgvector", "table": "idx_v1"},
        },
    )
    session.commit()

    fetched = session.get(RecipeVersion, rv.id)
    assert fetched is not None
    assert fetched.version_number == 1
    assert fetched.content["embedding"]["dimension"] == 768
    assert fetched.content["backend"]["kind"] == "pgvector"


def test_recipe_version_unique_per_source(session: Session) -> None:
    """Two recipe versions with the same number on the same source collide."""
    src = make_source(session)
    make_recipe_version(session, src, version_number=1)
    session.commit()
    with pytest.raises(IntegrityError):
        # The factory calls session.flush(), so the violation surfaces here.
        make_recipe_version(session, src, version_number=1)
    session.rollback()


def test_recipe_version_independent_per_source(session: Session) -> None:
    """Different sources can both have version 1, 2, ... independently."""
    src_a = make_source(session, slug="src-a")
    src_b = make_source(session, slug="src-b")
    make_recipe_version(session, src_a, version_number=1)
    make_recipe_version(session, src_b, version_number=1)
    make_recipe_version(session, src_a, version_number=2)
    session.commit()

    assert len(src_a.recipe_versions) == 2
    assert len(src_b.recipe_versions) == 1


def test_recipe_version_cascade_delete_with_source(session: Session) -> None:
    """Deleting a source cascades to its recipe versions."""
    src = make_source(session)
    rv = make_recipe_version(session, src)
    session.commit()
    rv_id = rv.id

    session.delete(src)
    session.commit()

    assert session.get(RecipeVersion, rv_id) is None
