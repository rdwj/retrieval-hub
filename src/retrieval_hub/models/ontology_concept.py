"""Ontology concept hierarchy model.

First-class canonical concept with optional parent/child (IS-A) edges.
The hierarchy is source-independent — a concept's position is the same
regardless of which source mentions it.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from retrieval_hub.db.base import Base


def _utcnow() -> datetime:
    return datetime.now(UTC)


class OntologyConcept(Base):
    """A canonical concept with an optional parent in the IS-A hierarchy."""

    __tablename__ = "ontology_concept"

    name: Mapped[str] = mapped_column(
        String(256), primary_key=True,
    )
    parent_name: Mapped[str | None] = mapped_column(
        String(256),
        ForeignKey("ontology_concept.name"),
        nullable=True,
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow,
    )
