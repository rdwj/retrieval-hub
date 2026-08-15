"""Pydantic response schemas matching the UI's TypeScript Source interface.

Every field that might not be populated from the database is Optional with a
sensible default so the BFF never crashes on sparse catalog data.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Nested types (alphabetical by UI interface name)
# ---------------------------------------------------------------------------


class AccessPolicy(BaseModel):
    visibility: str = "public"
    allowed_groups: list[str] = Field(default_factory=list)


class AgentWritePolicy(BaseModel):
    allowed: bool = False
    scope_required: str = ""
    allowed_groups: list[str] = Field(default_factory=list)
    write_modes: list[str] = Field(default_factory=list)
    write_validation: dict[str, Any] | None = None
    recent_write_activity_summary: str | None = None


class EvalResultEntry(BaseModel):
    llm: str
    recall_at_5: float = 0.0
    mrr: float = 0.0
    rewrite_lift_at_5: float | None = None
    source_system: str = "native"
    eval_run_id: str = ""
    mlflow_run_id: str | None = None
    run_at: str = ""


class HealthFlag(BaseModel):
    kind: str
    detail: str


class IngestionRunEntry(BaseModel):
    id: str
    status: str = "completed"
    started_at: str = ""
    duration_seconds: float = 0
    document_count: int = 0
    triggered_by: str = ""


class Lineage(BaseModel):
    origin_kind: str = "file_upload"
    origin_config: dict[str, Any] = Field(default_factory=dict)
    refresh_cadence: str = "on_demand"
    last_refresh_at: str | None = None
    next_scheduled_refresh_at: str | None = None
    ingestion_runs: list[IngestionRunEntry] = Field(default_factory=list)


class Owner(BaseModel):
    team: str = ""
    contacts: list[str] = Field(default_factory=list)
    maintainers: list[str] = Field(default_factory=list)


class PhysicalIndexInfo(BaseModel):
    id: str
    recipe_version: int = 0
    backend_kind: str = ""
    location: str = ""
    built_at: str | None = None
    document_count: int = 0
    health: str = "ok"


class Recipe(BaseModel):
    version: int = 0
    parser_kind: str = ""
    chunker_kind: str = ""
    chunker_summary: str = ""
    embedding_model: str = ""
    embedding_dimension: int = 0
    backend_kind: str = ""
    backend_location: str = ""
    raw_yaml: str = ""


class RecipeVersionEntry(BaseModel):
    version: int
    active_since: str = ""
    author: str = ""
    summary: str = ""


class RetrievalPatternConfig(BaseModel):
    pattern: str
    parameters: dict[str, Any] = Field(default_factory=dict)


class RewriterMetadata(BaseModel):
    enabled: bool = False
    shared_template_pointer: str | None = None
    shared_template_version: int | None = None
    vocabulary_mappings: list[dict[str, Any]] = Field(default_factory=list)
    sample_queries: list[dict[str, Any]] = Field(default_factory=list)
    domain_notes: str = ""
    schema_hints: dict[str, Any] | None = None
    prompt_override_id: str | None = None
    default_llm: str = ""
    llm_resolution: str = "default"
    max_rewrites: int = 0
    metadata_version: int = 1


class SamplePromptEntry(BaseModel):
    applies_to_llm_family: str
    role: str = "user"
    text: str = ""


# ---------------------------------------------------------------------------
# Top-level Source response
# ---------------------------------------------------------------------------


class SourceResponse(BaseModel):
    """Full source payload matching the UI's ``Source`` TypeScript interface."""

    id: str
    slug: str
    name: str
    family: str
    status: str

    owner: Owner = Field(default_factory=Owner)
    description_short: str = ""
    description_long: str = ""
    intended_use: str | None = None
    out_of_scope_use: str | None = None
    known_limitations: str | None = None
    domain_tags: list[str] = Field(default_factory=list)
    languages: list[str] = Field(default_factory=lambda: ["en"])
    citation_format: str | None = None

    created_at: str = ""
    updated_at: str = ""

    recipe: Recipe = Field(default_factory=Recipe)
    recipe_version_history: list[RecipeVersionEntry] = Field(default_factory=list)

    retrieval_default_pattern: str = "vector_ann"
    retrieval_supported_patterns: list[RetrievalPatternConfig] = Field(
        default_factory=list
    )

    active_physical_index: PhysicalIndexInfo | None = None
    size_summary: str = ""
    chunk_count_total: int | None = None

    evals: list[EvalResultEntry] = Field(default_factory=list)
    latency_p50_ms: int = 0
    latency_p95_ms: int = 0
    cost_estimate_hint: str | None = None

    rewriter: RewriterMetadata = Field(default_factory=RewriterMetadata)
    agent_write_policy: AgentWritePolicy = Field(default_factory=AgentWritePolicy)
    sample_prompts: list[SamplePromptEntry] = Field(default_factory=list)
    lineage: Lineage = Field(default_factory=Lineage)
    access: AccessPolicy = Field(default_factory=AccessPolicy)
    health_flags: list[HealthFlag] = Field(default_factory=list)

    usage_rules: dict[str, Any] | None = None
    mcp_endpoint: str | None = None
