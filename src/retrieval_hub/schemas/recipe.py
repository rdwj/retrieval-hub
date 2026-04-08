"""Pydantic schemas for recipe versions."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class RecipeVersionCreate(BaseModel):
    """Input shape for creating a new recipe version."""

    model_config = ConfigDict(extra="forbid")

    content: dict[str, Any] = Field(
        ..., description="Full recipe body (parser, chunker, embedding, backend, retrieval)."
    )
    created_by: str | None = None


class RecipeVersionRead(BaseModel):
    """Read shape for a recipe version row."""

    model_config = ConfigDict(extra="forbid", from_attributes=True)

    id: str
    source_id: str
    version_number: int
    content: dict[str, Any]
    created_at: datetime
    created_by: str | None = None
