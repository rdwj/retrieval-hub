"""Pydantic schemas for the ``Source`` table and its directly-owned children.

``SourceCard`` is the *browse-time* projection from ``docs/catalog.md`` —
small, dense, suitable for a list view. ``SourceRead`` is the full
*detail-time* projection. ``SourceCreate`` and ``SourceUpdate`` are the
write-side input shapes used by the (future) admin API.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from retrieval_hub.models.enums import (
    AccessVisibility,
    IndexHealth,
    PhysicalIndexBackend,
    PromptRole,
    SourceFamily,
    SourceStatus,
)
from retrieval_hub.schemas.common import (
    AccessPolicy,
    AgentWritePolicy,
    LineageOrigin,
)
from retrieval_hub.schemas.rewriter import RewriterMetadata


class SamplePromptRead(BaseModel):
    """Read shape for a sample prompt row."""

    model_config = ConfigDict(extra="forbid", from_attributes=True)

    id: str
    source_id: str
    applies_to_llm_family: str
    role: PromptRole
    text: str
    created_at: datetime


class PhysicalIndexRead(BaseModel):
    """Read shape for a physical index row."""

    model_config = ConfigDict(extra="forbid", from_attributes=True)

    id: str
    source_id: str
    recipe_version_id: str
    backend_kind: PhysicalIndexBackend
    location: str
    built_at: datetime
    health: IndexHealth
    document_count: int
    build_metadata: dict[str, Any] | None = None


class SourceCreate(BaseModel):
    """Input shape for creating a new ``Source``.

    A new source always starts in ``SourceStatus.DRAFT``; the API does not
    accept an explicit status on create.
    """

    model_config = ConfigDict(extra="forbid")

    slug: str = Field(..., min_length=1, max_length=128)
    name: str = Field(..., min_length=1, max_length=256)
    family: SourceFamily
    visibility: AccessVisibility = AccessVisibility.PUBLIC
    description_short: str | None = None
    description_long: str | None = None
    owner_team: str | None = None
    owner_contacts: list[str] = Field(default_factory=list)
    maintainers: list[str] = Field(default_factory=list)
    rewriter_metadata: RewriterMetadata | None = None
    agent_write_policy: AgentWritePolicy | None = None
    access: AccessPolicy | None = None
    lineage_origin: LineageOrigin | None = None
    refresh_cadence: str | None = None
    created_by: str | None = None

    @field_validator("slug")
    @classmethod
    def _slug_url_safe(cls, value: str) -> str:
        """Reject obviously invalid slugs (whitespace, slashes)."""
        if not value or any(c.isspace() for c in value) or "/" in value:
            raise ValueError("slug must be url-safe (no whitespace or slashes)")
        return value


class SourceUpdate(BaseModel):
    """Input shape for updating an existing ``Source``.

    Status transitions go through a separate explicit endpoint, not through
    this update shape, so the lifecycle rules in ``catalog.md`` are enforced
    in one place. ``slug`` and ``family`` are immutable.
    """

    model_config = ConfigDict(extra="forbid")

    name: str | None = None
    visibility: AccessVisibility | None = None
    description_short: str | None = None
    description_long: str | None = None
    owner_team: str | None = None
    owner_contacts: list[str] | None = None
    maintainers: list[str] | None = None
    rewriter_metadata: RewriterMetadata | None = None
    agent_write_policy: AgentWritePolicy | None = None
    access: AccessPolicy | None = None
    lineage_origin: LineageOrigin | None = None
    refresh_cadence: str | None = None
    updated_by: str | None = None


class SourceRead(BaseModel):
    """Full read shape for a ``Source`` row (the detail-page projection)."""

    model_config = ConfigDict(extra="forbid", from_attributes=True)

    id: str
    slug: str
    name: str
    family: SourceFamily
    status: SourceStatus
    visibility: AccessVisibility
    description_short: str | None = None
    description_long: str | None = None
    owner_team: str | None = None
    owner_contacts: list[str] | None = None
    maintainers: list[str] | None = None
    recipe_version_id: str | None = None
    active_physical_index_id: str | None = None
    rewriter_metadata: dict[str, Any] | None = None
    agent_write_policy: dict[str, Any] | None = None
    access: dict[str, Any] | None = None
    lineage_origin: dict[str, Any] | None = None
    refresh_cadence: str | None = None
    last_refresh_at: datetime | None = None
    created_at: datetime
    updated_at: datetime
    created_by: str | None = None
    updated_by: str | None = None


class SourceCard(BaseModel):
    """The browse-time projection of a source per ``docs/catalog.md``.

    Strictly a subset of ``SourceRead``. Card-level fields are picked because
    they are cheap to render in a list view and tell an agent developer enough
    to decide whether to dig in.
    """

    model_config = ConfigDict(extra="forbid", from_attributes=True)

    id: str
    slug: str
    name: str
    family: SourceFamily
    status: SourceStatus
    visibility: AccessVisibility
    description_short: str | None = None
    owner_team: str | None = None
    last_refresh_at: datetime | None = None
    rewrite_available: bool = False
    headline_scores: dict[str, Any] | None = None
