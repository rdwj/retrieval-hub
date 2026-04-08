"""Tests for the ``PhysicalIndex`` model and the active-index pointer on Source."""

from __future__ import annotations

from sqlalchemy.orm import Session

from retrieval_hub.models import PhysicalIndex, Source
from retrieval_hub.models.enums import IndexHealth, PhysicalIndexBackend
from tests.conftest import make_physical_index, make_recipe_version, make_source


def test_physical_index_creation(session: Session) -> None:
    """A physical index persists with its backend, location, and health."""
    src = make_source(session)
    rv = make_recipe_version(session, src)
    pi = make_physical_index(
        session,
        src,
        rv,
        backend_kind=PhysicalIndexBackend.PGVECTOR,
        location="idx_test_v1",
        document_count=42,
    )
    session.commit()

    fetched = session.get(PhysicalIndex, pi.id)
    assert fetched is not None
    assert fetched.source_id == src.id
    assert fetched.recipe_version_id == rv.id
    assert fetched.backend_kind == PhysicalIndexBackend.PGVECTOR
    assert fetched.health == IndexHealth.OK
    assert fetched.document_count == 42


def test_active_physical_index_pointer(session: Session) -> None:
    """A source can point at one of its physical indexes as 'active'."""
    src = make_source(session)
    rv = make_recipe_version(session, src)
    pi_one = make_physical_index(session, src, rv, location="idx_v1_a")
    pi_two = make_physical_index(session, src, rv, location="idx_v1_b")
    session.commit()

    src.active_physical_index_id = pi_two.id
    session.commit()

    refreshed = session.get(Source, src.id)
    assert refreshed is not None
    assert refreshed.active_physical_index_id == pi_two.id
    # Sanity: pi_one is still bound to the source via the children relationship.
    assert {p.id for p in refreshed.physical_indexes} == {pi_one.id, pi_two.id}


def test_physical_index_health_transition(session: Session) -> None:
    """Health field accepts the documented values."""
    src = make_source(session)
    rv = make_recipe_version(session, src)
    pi = make_physical_index(session, src, rv)
    pi.health = IndexHealth.DEGRADED
    session.commit()

    refreshed = session.get(PhysicalIndex, pi.id)
    assert refreshed is not None
    assert refreshed.health == IndexHealth.DEGRADED

    refreshed.health = IndexHealth.FAILED
    session.commit()
    refreshed = session.get(PhysicalIndex, pi.id)
    assert refreshed is not None
    assert refreshed.health == IndexHealth.FAILED


def test_physical_index_cascade_delete_with_source(session: Session) -> None:
    """Deleting a source cascades to its physical indexes."""
    src = make_source(session)
    rv = make_recipe_version(session, src)
    pi = make_physical_index(session, src, rv)
    session.commit()
    pi_id = pi.id

    # Clear the active pointer first to avoid the alter cycle.
    src.active_physical_index_id = None
    session.flush()
    session.delete(src)
    session.commit()

    assert session.get(PhysicalIndex, pi_id) is None
