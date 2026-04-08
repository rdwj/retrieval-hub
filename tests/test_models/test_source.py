"""Tests for the ``Source`` model: identity, validation, and lifecycle."""

from __future__ import annotations

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from retrieval_hub.models import Source
from retrieval_hub.models.enums import (
    AccessVisibility,
    SourceFamily,
    SourceStatus,
)
from retrieval_hub.models.source import InvalidStateTransitionError
from tests.conftest import make_source


def test_source_create_persists_with_defaults(session: Session) -> None:
    """A freshly inserted source carries its defaults and is round-trippable."""
    src = make_source(session, slug="rh-product-docs", name="Red Hat Product Docs")
    session.commit()

    fetched = session.get(Source, src.id)
    assert fetched is not None
    assert fetched.slug == "rh-product-docs"
    assert fetched.family == SourceFamily.DOCUMENT
    assert fetched.status == SourceStatus.DRAFT
    assert fetched.visibility == AccessVisibility.PUBLIC
    assert fetched.created_at is not None
    assert fetched.updated_at is not None


def test_source_slug_is_unique(session: Session) -> None:
    """Two sources cannot share a slug."""
    make_source(session, slug="dup-slug")
    session.commit()
    with pytest.raises(IntegrityError):
        # The factory calls session.flush(), so the violation surfaces here.
        make_source(session, slug="dup-slug")
    session.rollback()


@pytest.mark.parametrize(
    ("start", "end"),
    [
        (SourceStatus.DRAFT, SourceStatus.CURATED),
        (SourceStatus.DRAFT, SourceStatus.RETIRED),
        (SourceStatus.CURATED, SourceStatus.PUBLISHED),
        (SourceStatus.CURATED, SourceStatus.RETIRED),
        (SourceStatus.PUBLISHED, SourceStatus.CURATED),
        (SourceStatus.PUBLISHED, SourceStatus.RETIRED),
    ],
)
def test_source_allowed_transitions(
    session: Session, start: SourceStatus, end: SourceStatus
) -> None:
    """Allowed transitions per docs/catalog.md succeed."""
    src = make_source(session, status=start)
    src.transition_to(end)
    assert src.status == end


@pytest.mark.parametrize(
    ("start", "end"),
    [
        (SourceStatus.DRAFT, SourceStatus.PUBLISHED),  # must go through Curated
        (SourceStatus.RETIRED, SourceStatus.DRAFT),
        (SourceStatus.RETIRED, SourceStatus.CURATED),
        (SourceStatus.RETIRED, SourceStatus.PUBLISHED),
        (SourceStatus.CURATED, SourceStatus.DRAFT),  # no walk-back
    ],
)
def test_source_invalid_transitions_raise(
    session: Session, start: SourceStatus, end: SourceStatus
) -> None:
    """Disallowed transitions raise InvalidStateTransitionError."""
    src = make_source(session, status=start)
    with pytest.raises(InvalidStateTransitionError):
        src.transition_to(end)
    assert src.status == start


def test_source_transition_to_same_state_is_noop(session: Session) -> None:
    """Transitioning to the current state is allowed and changes nothing."""
    src = make_source(session, status=SourceStatus.CURATED)
    src.transition_to(SourceStatus.CURATED)
    assert src.status == SourceStatus.CURATED


def test_source_family_persisted_as_string(session: Session) -> None:
    """Family enum is stored as its string value, queryable both ways."""
    src = make_source(session, family=SourceFamily.CLINICAL_DOCUMENT)
    session.commit()

    fetched = session.get(Source, src.id)
    assert fetched is not None
    assert fetched.family == SourceFamily.CLINICAL_DOCUMENT
    assert fetched.family == "clinical_document"


def test_source_jsonb_fields_round_trip(session: Session) -> None:
    """JSONB columns survive a round trip with nested data intact."""
    src = make_source(
        session,
        access={"visibility": "restricted", "allowed_groups": ["clinical-agents"]},
        rewriter_metadata={
            "enabled": True,
            "vocabulary_mappings": [{"lay_term": "blood sugar", "canonical_term": "glycemia"}],
        },
        agent_write_policy={"allowed": False, "write_modes": []},
    )
    session.commit()

    fetched = session.get(Source, src.id)
    assert fetched is not None
    assert fetched.access == {
        "visibility": "restricted",
        "allowed_groups": ["clinical-agents"],
    }
    assert fetched.rewriter_metadata is not None
    assert fetched.rewriter_metadata["enabled"] is True
    assert fetched.agent_write_policy == {"allowed": False, "write_modes": []}
