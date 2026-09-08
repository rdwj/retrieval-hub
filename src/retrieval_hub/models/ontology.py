"""Ontology mapping ORM model.

Maps source-local concept names to canonical (enterprise-wide) concept names,
enabling cross-source ontology alignment. Each row says "in source X, the
local name Y corresponds to canonical concept Z."
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import DateTime, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from retrieval_hub.db.base import Base


def _utcnow() -> datetime:
    return datetime.now(UTC)


class OntologyMapping(Base):
    """A mapping from a source-local concept name to a canonical name."""

    __tablename__ = "ontology_mapping"
    __table_args__ = (
        UniqueConstraint(
            "canonical_name",
            "source_slug",
            "local_name",
            name="uq_ontology_mapping_canonical_source_local",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    canonical_name: Mapped[str] = mapped_column(
        String(256), nullable=False, index=True
    )
    source_slug: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    local_name: Mapped[str] = mapped_column(String(256), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )
