"""Output schemas for rewriter LLM responses.

These model the structured output the LLM produces -- distinct from
``retrieval_hub.schemas.rewriter.RewriterMetadata`` which captures
source-owner-declared *input* configuration.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class RewrittenQuery(BaseModel):
    """A single rewritten query variant produced by the LLM."""

    model_config = ConfigDict(extra="forbid")

    text: str
    intent: str
    rationale: str
    confidence: float = Field(ge=0.0, le=1.0)


class RewriteResult(BaseModel):
    """Complete result from a rewrite operation, including lineage."""

    model_config = ConfigDict(extra="forbid")

    queries: list[RewrittenQuery]
    raw_query: str
    template_version: str
    metadata_version: str | None = None
    llm: str
    request_id: str
