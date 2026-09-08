"""Ontology cross-concept relationship model.

Stores canonical relationships between concepts: (source_concept, verb,
target_concept).  Source-independent when source_slug is null; source-
specific observations carry the slug of the source where the edge was
observed.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import DateTime, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from retrieval_hub.db.base import Base


def _utcnow() -> datetime:
    return datetime.now(UTC)


class OntologyRelationship(Base):
    """A directed relationship between two canonical concepts."""

    __tablename__ = "ontology_relationship"
    __table_args__ = (
        UniqueConstraint(
            "source_concept",
            "relationship",
            "target_concept",
            "source_slug",
            name="uq_ontology_rel_src_rel_tgt_slug",
        ),
    )

    id: Mapped[int] = mapped_column(
        Integer, autoincrement=True, primary_key=True,
    )
    source_concept: Mapped[str] = mapped_column(
        String(256), nullable=False, index=True,
    )
    relationship: Mapped[str] = mapped_column(
        String(256), nullable=False,
    )
    target_concept: Mapped[str] = mapped_column(
        String(256), nullable=False, index=True,
    )
    source_slug: Mapped[str | None] = mapped_column(
        String(128), nullable=True, index=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow,
    )
