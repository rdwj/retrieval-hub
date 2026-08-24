"""ORM models for the central ``Source`` table and its directly-owned children.

A ``Source`` is the heart of the catalog. It carries identity, lifecycle,
ownership, recipe pointer, active physical index pointer, rewriter metadata,
agent write policy, access policy, and lineage. ``SamplePrompt`` and
``PhysicalIndex`` are owned by a Source and stored as separate tables.

State transition rules are enforced by ``Source.transition_to``. The graph is:

    Draft -> Curated -> Published
    Curated <-> Published
    Draft   -> Retired
    Curated -> Retired
    Published -> Retired
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
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from retrieval_hub.db.base import Base
from retrieval_hub.db.types import JSONType
from retrieval_hub.models.enums import (
    AccessVisibility,
    IndexHealth,
    PhysicalIndexBackend,
    PromptRole,
    SourceFamily,
    SourceStatus,
)

if TYPE_CHECKING:
    from sqlalchemy.orm import Session as SASession

    from retrieval_hub.models.recipe import RecipeVersion


# ---------------------------------------------------------------------------
# Lifecycle transitions
# ---------------------------------------------------------------------------

# Allowed forward transitions per docs/catalog.md "Source lifecycle".
_ALLOWED_TRANSITIONS: dict[SourceStatus, frozenset[SourceStatus]] = {
    SourceStatus.DRAFT: frozenset({SourceStatus.CURATED, SourceStatus.RETIRED}),
    SourceStatus.CURATED: frozenset({SourceStatus.PUBLISHED, SourceStatus.RETIRED}),
    SourceStatus.PUBLISHED: frozenset({SourceStatus.CURATED, SourceStatus.RETIRED}),
    SourceStatus.RETIRED: frozenset(),
}


class InvalidStateTransitionError(ValueError):
    """Raised when a caller attempts an unsupported source lifecycle transition."""


def _new_uuid() -> str:
    """Return a new opaque source identifier as a string."""
    return str(uuid.uuid4())


def _utcnow() -> datetime:
    """Return a timezone-aware UTC ``now`` for default columns."""
    return datetime.now(UTC)


# ---------------------------------------------------------------------------
# Source
# ---------------------------------------------------------------------------


class Source(Base):
    """A published, recipe-documented retrieval surface."""

    __tablename__ = "source"
    __table_args__ = (
        UniqueConstraint("slug", name="uq_source_slug"),
        Index("ix_source_status", "status"),
        Index("ix_source_family", "family"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=_new_uuid)
    slug: Mapped[str] = mapped_column(String(128), nullable=False)
    name: Mapped[str] = mapped_column(String(256), nullable=False)
    family: Mapped[SourceFamily] = mapped_column(String(32), nullable=False)
    status: Mapped[SourceStatus] = mapped_column(
        String(32), nullable=False, default=SourceStatus.DRAFT
    )
    visibility: Mapped[AccessVisibility] = mapped_column(
        String(32), nullable=False, default=AccessVisibility.PUBLIC
    )

    description_short: Mapped[str | None] = mapped_column(Text, nullable=True)
    description_long: Mapped[str | None] = mapped_column(Text, nullable=True)

    owner_team: Mapped[str | None] = mapped_column(String(128), nullable=True)
    owner_contacts: Mapped[list[str] | None] = mapped_column(JSONType, nullable=True)
    maintainers: Mapped[list[str] | None] = mapped_column(JSONType, nullable=True)

    # Pointer to the currently active recipe version. Nullable while in Draft
    # before any recipe has been authored.
    recipe_version_id: Mapped[str | None] = mapped_column(
        String(64),
        ForeignKey("recipe_version.id", name="fk_source_recipe_version_id_recipe_version"),
        nullable=True,
    )

    # Pointer to the active physical index. Nullable while in Draft.
    active_physical_index_id: Mapped[str | None] = mapped_column(
        String(64),
        ForeignKey(
            "physical_index.id",
            name="fk_source_active_physical_index_id_physical_index",
            use_alter=True,
        ),
        nullable=True,
    )

    rewriter_metadata: Mapped[dict[str, Any] | None] = mapped_column(JSONType, nullable=True)
    agent_write_policy: Mapped[dict[str, Any] | None] = mapped_column(JSONType, nullable=True)
    usage_rules: Mapped[dict[str, Any] | None] = mapped_column(JSONType, nullable=True)
    semantic_context: Mapped[dict[str, Any] | None] = mapped_column(JSONType, nullable=True)
    access: Mapped[dict[str, Any] | None] = mapped_column(JSONType, nullable=True)
    lineage_origin: Mapped[dict[str, Any] | None] = mapped_column(JSONType, nullable=True)

    refresh_cadence: Mapped[str | None] = mapped_column(String(64), nullable=True)
    last_refresh_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow, onupdate=_utcnow
    )
    created_by: Mapped[str | None] = mapped_column(String(128), nullable=True)
    updated_by: Mapped[str | None] = mapped_column(String(128), nullable=True)

    # Relationships
    recipe_versions: Mapped[list[RecipeVersion]] = relationship(
        "RecipeVersion",
        back_populates="source",
        cascade="all, delete-orphan",
        foreign_keys="RecipeVersion.source_id",
    )
    physical_indexes: Mapped[list[PhysicalIndex]] = relationship(
        "PhysicalIndex",
        back_populates="source",
        cascade="all, delete-orphan",
        foreign_keys="PhysicalIndex.source_id",
    )
    sample_prompts: Mapped[list[SamplePrompt]] = relationship(
        "SamplePrompt",
        back_populates="source",
        cascade="all, delete-orphan",
    )

    def transition_to(
        self,
        new_status: SourceStatus,
        *,
        session: SASession | None = None,
        actor: str | None = None,
    ) -> None:
        """Move the source to ``new_status`` if the transition is allowed.

        When *session* is provided, an audit record is written for the
        status change (but not committed -- the caller owns the transaction).

        Raises ``InvalidStateTransitionError`` if the transition is not in the
        catalog.md state graph.
        """
        if new_status == self.status:
            return
        allowed = _ALLOWED_TRANSITIONS.get(self.status, frozenset())
        if new_status not in allowed:
            raise InvalidStateTransitionError(
                f"Cannot transition source {self.slug!r} from {self.status} to {new_status}. "
                f"Allowed: {sorted(allowed)}"
            )
        old_status = self.status
        self.status = new_status
        if session is not None:
            from retrieval_hub.audit import write_audit_record

            write_audit_record(
                session,
                action="source.status_changed",
                source_id=self.id,
                actor=actor,
                details={
                    "slug": self.slug,
                    "old_status": old_status.value,
                    "new_status": new_status.value,
                },
            )


# ---------------------------------------------------------------------------
# SamplePrompt
# ---------------------------------------------------------------------------


class SamplePrompt(Base):
    """A sample prompt advertised by a source for a given LLM family."""

    __tablename__ = "sample_prompt"
    __table_args__ = (
        Index("ix_sample_prompt_source_id", "source_id"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=_new_uuid)
    source_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("source.id", name="fk_sample_prompt_source_id_source", ondelete="CASCADE"),
        nullable=False,
    )
    applies_to_llm_family: Mapped[str] = mapped_column(String(128), nullable=False)
    role: Mapped[PromptRole] = mapped_column(String(32), nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )

    source: Mapped[Source] = relationship("Source", back_populates="sample_prompts")


# ---------------------------------------------------------------------------
# PhysicalIndex
# ---------------------------------------------------------------------------


class PhysicalIndex(Base):
    """A built realization of one recipe version against a data snapshot."""

    __tablename__ = "physical_index"
    __table_args__ = (
        Index("ix_physical_index_source_id", "source_id"),
        Index("ix_physical_index_recipe_version_id", "recipe_version_id"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=_new_uuid)
    source_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey(
            "source.id",
            name="fk_physical_index_source_id_source",
            ondelete="CASCADE",
        ),
        nullable=False,
    )
    recipe_version_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey(
            "recipe_version.id",
            name="fk_physical_index_recipe_version_id_recipe_version",
        ),
        nullable=False,
    )
    backend_kind: Mapped[PhysicalIndexBackend] = mapped_column(String(32), nullable=False)
    location: Mapped[str] = mapped_column(String(512), nullable=False)
    built_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )
    health: Mapped[IndexHealth] = mapped_column(
        String(32), nullable=False, default=IndexHealth.OK
    )
    document_count: Mapped[int] = mapped_column(nullable=False, default=0)
    build_metadata: Mapped[dict[str, Any] | None] = mapped_column(JSONType, nullable=True)

    source: Mapped[Source] = relationship(
        "Source", back_populates="physical_indexes", foreign_keys=[source_id]
    )
    recipe_version: Mapped[RecipeVersion] = relationship(
        "RecipeVersion", back_populates="physical_indexes"
    )
