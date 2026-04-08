"""Pydantic schemas for rewriter metadata and override prompt references."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from retrieval_hub.models.enums import LlmResolution


class VocabularyMapping(BaseModel):
    """A single ``(lay_term, canonical_term)`` mapping for the rewriter."""

    model_config = ConfigDict(extra="forbid")

    lay_term: str
    canonical_term: str


class SampleQueryExample(BaseModel):
    """A few-shot example used by the shared rewriter template."""

    model_config = ConfigDict(extra="forbid")

    raw: str
    good_rewrites: list[str] = Field(default_factory=list)


class RewriterMetadata(BaseModel):
    """Per-source rewriter metadata stored on ``Source.rewriter_metadata``."""

    model_config = ConfigDict(extra="forbid")

    enabled: bool = False
    vocabulary_mappings: list[VocabularyMapping] = Field(default_factory=list)
    domain_notes: str | None = None
    sample_queries: list[SampleQueryExample] = Field(default_factory=list)
    schema_hints: dict[str, Any] | None = None
    prompt_override_id: str | None = None
    llm_resolution: LlmResolution = LlmResolution.DEFAULT
    default_llm: str | None = None
    max_rewrites: int = 5


class RewritePromptRefRead(BaseModel):
    """Read shape for an MLflow-registered (or fallback) override prompt reference."""

    model_config = ConfigDict(extra="forbid", from_attributes=True)

    id: str
    source_id: str
    prompt_slug: str
    active_version: int
    created_at: datetime
