"""Pydantic response models for RetrievalHub MCP tools.

These schemas define the structured output shape that agents receive from
each tool. They are intentionally decoupled from the SQLAlchemy ORM models
so the MCP layer can evolve independently of the catalog schema.
"""

from __future__ import annotations

from pydantic import BaseModel


class SourceSummary(BaseModel):
    """Compact catalog entry returned by ``list_sources``."""

    slug: str
    name: str
    family: str
    status: str
    description_short: str | None = None
    document_count: int | None = None


class SourceDetail(BaseModel):
    """Full metadata for a single source, returned by ``describe_source``."""

    slug: str
    name: str
    family: str
    status: str
    description_short: str | None = None
    description_long: str | None = None
    owner_team: str | None = None
    document_count: int | None = None
    chunk_count: int | None = None
    recipe_content: dict | None = None
    sample_prompts: list[dict] | None = None


class RetrievalHit(BaseModel):
    """One retrieval result with provenance metadata."""

    text: str
    score: float
    doc_title: str
    doc_url: str
    doc_section: str | None = None
    chunk_index: int | None = None
    physical_index_id: str
    recipe_version: int
    request_id: str


class UsageRules(BaseModel):
    """Per-source rules that govern how retrieved data should be used.

    Authored by the data owner.  Returned with every retrieval so the
    consuming agent always sees the obligations that come with this data.
    """

    citation: str | None = None
    scope_disclaimer: str | None = None
    handling: str | None = None
    custom_rules: list[str] | None = None


class DataFreshness(BaseModel):
    """Staleness metadata for the source's physical index."""

    source_name: str
    source_url: str | None = None
    last_refreshed: str | None = None
    refresh_cadence: str | None = None
    staleness_note: str | None = None


class RewrittenQueryInfo(BaseModel):
    """Summary of a single rewritten query, returned for observability."""

    text: str
    intent: str
    confidence: float


class RefineHit(BaseModel):
    """One chunk from a refinement expansion."""

    text: str
    doc_section: str | None = None
    chunk_index: int
    is_origin: bool


class RefineResponse(BaseModel):
    """Response from the ``refine`` tool.

    Contains the expanded context chunks ordered by document position,
    with the original chunk marked via ``is_origin``.  Document-level
    fields (``doc_title``, ``doc_url``) live on the envelope, not
    per-chunk, since all chunks come from the same document.
    """

    source: str
    doc_title: str
    doc_url: str
    origin_chunk_index: int
    strategy: str
    chunks: list[RefineHit]
    usage_rules: UsageRules | None = None
    data_freshness: DataFreshness | None = None


class RetrievalResponse(BaseModel):
    """Full retrieve response: hits plus source-level metadata.

    ``usage_rules`` tells the agent how the data owner requires their
    content to be cited, disclaimed, and handled.  ``data_freshness``
    communicates how current the index is.  Both ride with every
    retrieval so the agent cannot miss them.
    """

    hits: list[RetrievalHit]
    usage_rules: UsageRules | None = None
    data_freshness: DataFreshness | None = None
    rewritten_queries: list[RewrittenQueryInfo] | None = None
