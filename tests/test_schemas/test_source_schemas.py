"""Tests for Pydantic source schemas: create, update, read, card."""

from __future__ import annotations

import pytest
from pydantic import ValidationError
from sqlalchemy.orm import Session

from retrieval_hub.models.enums import (
    AccessVisibility,
    SourceFamily,
    WriteMode,
)
from retrieval_hub.schemas import (
    AccessPolicy,
    AgentWritePolicy,
    SourceCard,
    SourceCreate,
    SourceRead,
    SourceUpdate,
)
from retrieval_hub.schemas.rewriter import RewriterMetadata, VocabularyMapping
from tests.conftest import make_source


def test_source_create_minimal_valid() -> None:
    """A minimal SourceCreate parses cleanly with defaults applied."""
    payload = SourceCreate(
        slug="rh-product-docs",
        name="Red Hat Product Docs",
        family=SourceFamily.DOCUMENT,
    )
    assert payload.slug == "rh-product-docs"
    assert payload.visibility == AccessVisibility.PUBLIC
    assert payload.owner_contacts == []


def test_source_create_rejects_whitespace_slug() -> None:
    """Slugs with whitespace are rejected by the validator."""
    with pytest.raises(ValidationError):
        SourceCreate(slug="bad slug", name="Bad", family=SourceFamily.DOCUMENT)


def test_source_create_rejects_slash_in_slug() -> None:
    """Slugs containing slashes are rejected (not URL-safe)."""
    with pytest.raises(ValidationError):
        SourceCreate(slug="bad/slug", name="Bad", family=SourceFamily.DOCUMENT)


def test_source_create_rejects_unknown_field() -> None:
    """Extra fields are forbidden so callers get explicit errors on typos."""
    with pytest.raises(ValidationError):
        SourceCreate.model_validate(
            {
                "slug": "x",
                "name": "x",
                "family": "document",
                "definitely_not_a_field": True,
            }
        )


def test_source_read_from_orm_round_trip(session: Session) -> None:
    """An ORM Source projects cleanly into a SourceRead via from_attributes."""
    src = make_source(
        session,
        slug="va-clinical",
        name="VA Clinical Practice Guidelines",
        family=SourceFamily.CLINICAL_DOCUMENT,
    )
    session.commit()

    read = SourceRead.model_validate(src)
    assert read.slug == "va-clinical"
    assert read.family == SourceFamily.CLINICAL_DOCUMENT
    assert read.id == src.id


def test_source_card_projection_subset(session: Session) -> None:
    """SourceCard contains the browse-time subset of fields and nothing else."""
    src = make_source(session, slug="card-src", name="Card Src")
    session.commit()

    card = SourceCard.model_validate(src)
    assert card.id == src.id
    assert card.slug == "card-src"
    assert card.family == SourceFamily.DOCUMENT
    # Card-only fields default sensibly
    assert card.rewrite_available is False
    assert card.headline_scores is None
    # Non-card fields are not present on the model
    assert "description_long" not in card.model_dump()


def test_source_update_partial() -> None:
    """SourceUpdate allows partial updates without requiring all fields."""
    update = SourceUpdate(name="New Name", refresh_cadence="weekly")
    dumped = update.model_dump(exclude_unset=True)
    assert dumped == {"name": "New Name", "refresh_cadence": "weekly"}


def test_rewriter_metadata_nested_validation() -> None:
    """RewriterMetadata correctly validates nested vocabulary mappings."""
    rm = RewriterMetadata(
        enabled=True,
        vocabulary_mappings=[
            VocabularyMapping(lay_term="high blood sugar", canonical_term="hyperglycemia"),
        ],
    )
    assert rm.enabled is True
    assert rm.vocabulary_mappings[0].canonical_term == "hyperglycemia"


def test_agent_write_policy_default_denies() -> None:
    """An AgentWritePolicy created without args defaults to deny."""
    policy = AgentWritePolicy()
    assert policy.allowed is False
    assert policy.write_modes == []
    assert policy.scope_required == "sources.write"


def test_access_policy_default_public() -> None:
    """An AccessPolicy created without args defaults to public visibility."""
    policy = AccessPolicy()
    assert policy.visibility == AccessVisibility.PUBLIC
    assert policy.allowed_groups == []


def test_agent_write_policy_with_modes() -> None:
    """An AgentWritePolicy carries WriteMode values that round-trip via model_dump."""
    policy = AgentWritePolicy(
        allowed=True,
        allowed_groups=["clinical-agents"],
        write_modes=[WriteMode.APPEND, WriteMode.ANNOTATE],
    )
    dumped = policy.model_dump()
    assert dumped["allowed"] is True
    assert dumped["write_modes"] == ["append", "annotate"]
