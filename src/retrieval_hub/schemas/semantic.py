"""Per-source semantic layer: domain knowledge that augments retrieval.

General-purpose schema that works for clinical, code, legal, or any domain.
All type fields are free-text strings, not domain-specific enums, so no
schema update is needed when onboarding a new domain.

Stored on ``Source.semantic_context`` as a JSON column.  The rewriter
selectively injects entities, abbreviations, and metrics into its prompt;
relationships and domain_context are available for other consumers.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class EntityDefinition(BaseModel):
    """A named concept in the source's domain."""

    model_config = ConfigDict(extra="forbid")

    name: str
    entity_type: str
    definition: str
    aliases: list[str] = Field(default_factory=list)
    attributes: dict[str, Any] | None = None


class RelationshipHint(BaseModel):
    """A directed or bidirectional link between two entities."""

    model_config = ConfigDict(extra="forbid")

    source_entity: str
    target_entity: str
    relationship_type: str
    description: str | None = None
    directionality: str = "directed"


class MetricThreshold(BaseModel):
    """A single labeled threshold within a metric."""

    model_config = ConfigDict(extra="forbid")

    label: str
    value: str
    context: str | None = None


class MetricDefinition(BaseModel):
    """A quantitative measure with named thresholds."""

    model_config = ConfigDict(extra="forbid")

    name: str
    metric_type: str
    definition: str
    unit: str | None = None
    thresholds: list[MetricThreshold] = Field(default_factory=list)


class RefinementStrategy(BaseModel):
    """Configuration for a single refinement strategy.

    Data owners add these to ``SemanticContext.refinement_strategies`` to
    control how the ``refine`` tool expands context for their source.
    """

    model_config = ConfigDict(extra="forbid")

    kind: str
    window: int = 2
    enabled: bool = True


class SemanticContext(BaseModel):
    """Per-source semantic layer stored on ``Source.semantic_context``."""

    model_config = ConfigDict(extra="forbid")

    entities: list[EntityDefinition] = Field(default_factory=list)
    relationships: list[RelationshipHint] = Field(default_factory=list)
    metrics: list[MetricDefinition] = Field(default_factory=list)
    abbreviations: dict[str, str] = Field(default_factory=dict)
    domain_context: str | None = None
    refinement_strategies: list[RefinementStrategy] = Field(default_factory=list)
