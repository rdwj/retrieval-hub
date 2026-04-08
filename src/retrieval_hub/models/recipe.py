"""ORM models for recipes.

Per ``docs/catalog.md`` a *recipe* is the parameterization of how a source is
built (parser, chunker, embedding model, backend, retrieval-pattern config).
Recipes are versioned: each meaningful change produces a new ``RecipeVersion``
row, and the parent ``Source.recipe_version_id`` points at the active one.

We deliberately do not break the recipe body out into typed columns. The body
shape varies per source family and is expected to evolve; storing it as a JSON
blob keeps schema migrations from coupling to recipe-shape changes.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Index,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from retrieval_hub.db.base import Base
from retrieval_hub.db.types import JSONType

if TYPE_CHECKING:
    from retrieval_hub.models.source import PhysicalIndex, Source


def _new_uuid() -> str:
    return str(uuid.uuid4())


def _utcnow() -> datetime:
    return datetime.now(UTC)


class RecipeVersion(Base):
    """One immutable version of a source's recipe body."""

    __tablename__ = "recipe_version"
    __table_args__ = (
        UniqueConstraint(
            "source_id", "version_number", name="uq_recipe_version_source_id_version_number"
        ),
        Index("ix_recipe_version_source_id", "source_id"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=_new_uuid)
    source_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey(
            "source.id",
            name="fk_recipe_version_source_id_source",
            ondelete="CASCADE",
        ),
        nullable=False,
    )
    version_number: Mapped[int] = mapped_column(nullable=False)
    content: Mapped[dict[str, Any]] = mapped_column(JSONType, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )
    created_by: Mapped[str | None] = mapped_column(String(128), nullable=True)

    source: Mapped[Source] = relationship(
        "Source", back_populates="recipe_versions", foreign_keys=[source_id]
    )
    physical_indexes: Mapped[list[PhysicalIndex]] = relationship(
        "PhysicalIndex", back_populates="recipe_version"
    )


# Type alias kept so callers that imported ``Recipe`` from this module continue
# to work after we collapsed the "logical recipe" abstraction into the source
# row + versioned blob model. There is no separate ``Recipe`` table.
Recipe = RecipeVersion
