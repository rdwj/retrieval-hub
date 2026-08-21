"""Enumerations used throughout the retrieval-hub catalog data model.

These are ``StrEnum`` so they serialize cleanly into JSON and into SQLAlchemy
``String`` columns. Storing enums as strings (rather than native database
ENUM types) keeps migrations portable across PostgreSQL and SQLite, which is
the platform we run tests on.
"""

from __future__ import annotations

from enum import StrEnum


class SourceFamily(StrEnum):
    """Hard discriminator that selects the source adapter at retrieval time."""

    DOCUMENT = "document"
    CLINICAL_DOCUMENT = "clinical_document"
    TECHNICAL_DOCUMENT = "technical_document"
    CODE = "code"
    TABULAR = "tabular"
    GRAPH = "graph"
    PROCESS = "process"
    EXTERNAL = "external"


class SourceStatus(StrEnum):
    """Lifecycle states for a source. See catalog.md for transition rules."""

    DRAFT = "draft"
    CURATED = "curated"
    PUBLISHED = "published"
    RETIRED = "retired"


class AccessVisibility(StrEnum):
    """Visibility surface for a source's access policy."""

    PUBLIC = "public"
    RESTRICTED = "restricted"


class RetrievalPattern(StrEnum):
    """Named retrieval patterns a source family can advertise."""

    VECTOR_ANN = "vector_ann"
    VECTOR_WITH_FILTERS = "vector_with_filters"
    GRAPH_TRAVERSE_FROM_SEED = "graph_traverse_from_seed"
    STRUCTURED_QUERY = "structured_query"
    HYBRID = "hybrid"
    PASSTHROUGH_EXTERNAL = "passthrough_external"


class WriteMode(StrEnum):
    """Agent-facing data write modes governed by ``agent_write_policy``."""

    APPEND = "append"
    UPSERT = "upsert"
    ANNOTATE = "annotate"


class PromptRole(StrEnum):
    """Role label for a sample prompt entry."""

    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"


class PhysicalIndexBackend(StrEnum):
    """Backend kind for a physical index."""

    PGVECTOR = "pgvector"
    GRAPH = "graph"
    TABULAR = "tabular"
    EXTERNAL = "external"


class IndexHealth(StrEnum):
    """Health status of a built physical index."""

    OK = "ok"
    DEGRADED = "degraded"
    FAILED = "failed"


class EvalSuiteFamily(StrEnum):
    """Family discriminator on an eval suite (mirrors ``SourceFamily``)."""

    DOCUMENT = "document"
    CLINICAL_DOCUMENT = "clinical_document"
    TECHNICAL_DOCUMENT = "technical_document"
    CODE = "code"
    TABULAR = "tabular"
    GRAPH = "graph"
    PROCESS = "process"
    EXTERNAL = "external"


class EvalRunStatus(StrEnum):
    """Lifecycle status of an eval run."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class ExecutionBackend(StrEnum):
    """Where eval execution happened."""

    LLAMASTACK = "llamastack"
    NATIVE = "native"


class MlflowSyncState(StrEnum):
    """Whether an eval run has been mirrored to MLflow."""

    SYNCED = "synced"
    PENDING = "pending"
    FAILED = "failed"


class IngestionStatus(StrEnum):
    """Lifecycle status of an ingestion run."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class RefreshMode(StrEnum):
    """How an ingestion run produces a new realization of a source."""

    FULL_REBUILD = "full_rebuild"
    INCREMENTAL = "incremental"
    MIRROR_UPSERT = "mirror_upsert"


class TriggeredByKind(StrEnum):
    """What kind of identity initiated an asynchronous run."""

    USER = "user"
    AGENT = "agent"
    SERVICE = "service"
    SCHEDULER = "scheduler"


class LlmResolution(StrEnum):
    """How the rewriter chooses an LLM for a given source."""

    DEFAULT = "default"
    CALLER_REQUIRED = "caller_required"
    CALLER_OPTIONAL = "caller_optional"
