"""Shared Pydantic v2 schema fragments used across the catalog API."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from retrieval_hub.models.enums import AccessVisibility, WriteMode


class ErrorCode(StrEnum):
    """Reserved error codes for the catalog API surface."""

    SOURCE_NOT_FOUND = "SOURCE_NOT_FOUND"
    SOURCE_RETIRED = "SOURCE_RETIRED"
    INVALID_STATE_TRANSITION = "INVALID_STATE_TRANSITION"
    ACCESS_DENIED = "ACCESS_DENIED"
    WRITE_DENIED = "WRITE_DENIED"
    UNSUPPORTED_RETRIEVAL_PATTERN = "UNSUPPORTED_RETRIEVAL_PATTERN"
    PUBLISH_REQUIREMENTS_NOT_MET = "PUBLISH_REQUIREMENTS_NOT_MET"
    VALIDATION_ERROR = "VALIDATION_ERROR"


class OwnerInfo(BaseModel):
    """Owner team plus contacts and maintainers."""

    model_config = ConfigDict(extra="forbid")

    team: str | None = None
    contacts: list[str] = Field(default_factory=list)
    maintainers: list[str] = Field(default_factory=list)


class LineageOrigin(BaseModel):
    """Where the underlying data came from."""

    model_config = ConfigDict(extra="forbid")

    kind: str
    config: dict[str, Any] = Field(default_factory=dict)


class LineageRefresh(BaseModel):
    """Refresh-cadence projection for a source."""

    model_config = ConfigDict(extra="forbid")

    cadence: str | None = None
    last_refresh_at: datetime | None = None
    last_refresh_run_id: str | None = None


class Lineage(BaseModel):
    """Aggregated lineage information for a source."""

    model_config = ConfigDict(extra="forbid")

    origin: LineageOrigin | None = None
    refresh: LineageRefresh | None = None


class AccessPolicy(BaseModel):
    """Source-level access policy. Used by ``policy.access``."""

    model_config = ConfigDict(extra="forbid")

    visibility: AccessVisibility = AccessVisibility.PUBLIC
    allowed_groups: list[str] = Field(default_factory=list)
    allowed_identities: list[str] = Field(default_factory=list)


class AgentWritePolicy(BaseModel):
    """Source-level agent write policy. Used by ``policy.writes``."""

    model_config = ConfigDict(extra="forbid")

    allowed: bool = False
    scope_required: str = "sources.write"
    allowed_groups: list[str] = Field(default_factory=list)
    write_modes: list[WriteMode] = Field(default_factory=list)
    write_validation: dict[str, Any] | None = None
