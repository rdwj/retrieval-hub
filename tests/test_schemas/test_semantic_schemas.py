"""Tests for the per-source semantic layer schema."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from retrieval_hub.schemas.semantic import (
    EntityDefinition,
    MetricDefinition,
    MetricThreshold,
    RefinementStrategy,
    RelationshipHint,
    SemanticContext,
)


class TestEntityDefinition:
    def test_minimal(self):
        e = EntityDefinition(name="PTSD", entity_type="condition", definition="A disorder.")
        assert e.name == "PTSD"
        assert e.aliases == []
        assert e.attributes is None

    def test_with_aliases_and_attributes(self):
        e = EntityDefinition(
            name="PHQ-9",
            entity_type="screening_instrument",
            definition="Depression severity measure.",
            aliases=["Patient Health Questionnaire"],
            attributes={"scoring": {"mild": "5-9", "severe": "20-27"}},
        )
        assert len(e.aliases) == 1
        assert e.attributes["scoring"]["severe"] == "20-27"

    def test_rejects_extra_fields(self):
        with pytest.raises(ValidationError):
            EntityDefinition(
                name="x", entity_type="y", definition="z", unknown_field="bad"
            )


class TestRelationshipHint:
    def test_defaults(self):
        r = RelationshipHint(
            source_entity="PTSD",
            target_entity="SUD",
            relationship_type="comorbidity",
        )
        assert r.directionality == "directed"
        assert r.description is None

    def test_bidirectional(self):
        r = RelationshipHint(
            source_entity="A",
            target_entity="B",
            relationship_type="depends_on",
            directionality="bidirectional",
            description="Mutual dependency.",
        )
        assert r.directionality == "bidirectional"


class TestMetricDefinition:
    def test_with_thresholds(self):
        m = MetricDefinition(
            name="HbA1c",
            metric_type="clinical_threshold",
            definition="Glycated hemoglobin target.",
            unit="%",
            thresholds=[
                MetricThreshold(label="general", value="<7.0"),
                MetricThreshold(label="elderly", value="<8.0", context="age 60+"),
            ],
        )
        assert len(m.thresholds) == 2
        assert m.thresholds[1].context == "age 60+"

    def test_no_thresholds(self):
        m = MetricDefinition(
            name="Coverage",
            metric_type="test_coverage",
            definition="Test coverage percentage.",
        )
        assert m.thresholds == []
        assert m.unit is None


class TestRefinementStrategy:
    def test_defaults(self):
        s = RefinementStrategy(kind="adjacent")
        assert s.kind == "adjacent"
        assert s.window == 2
        assert s.enabled is True

    def test_custom_window(self):
        s = RefinementStrategy(kind="adjacent", window=5, enabled=False)
        assert s.window == 5
        assert s.enabled is False

    def test_rejects_extra_fields(self):
        with pytest.raises(ValidationError):
            RefinementStrategy(kind="adjacent", unknown="bad")

    def test_kind_required(self):
        with pytest.raises(ValidationError):
            RefinementStrategy()


class TestSemanticContext:
    def test_empty(self):
        ctx = SemanticContext()
        assert ctx.entities == []
        assert ctx.relationships == []
        assert ctx.metrics == []
        assert ctx.abbreviations == {}
        assert ctx.domain_context is None
        assert ctx.refinement_strategies == []

    def test_round_trip(self):
        ctx = SemanticContext(
            entities=[
                EntityDefinition(name="A", entity_type="t", definition="d", aliases=["a1"]),
            ],
            relationships=[
                RelationshipHint(source_entity="A", target_entity="B", relationship_type="r"),
            ],
            metrics=[
                MetricDefinition(
                    name="M",
                    metric_type="threshold",
                    definition="d",
                    thresholds=[MetricThreshold(label="ok", value="<5")],
                ),
            ],
            abbreviations={"ABC": "Always Be Coding"},
            domain_context="Test domain.",
        )
        data = ctx.model_dump(mode="json")
        restored = SemanticContext.model_validate(data)
        assert restored == ctx

    def test_with_refinement_strategies(self):
        ctx = SemanticContext(
            refinement_strategies=[
                RefinementStrategy(kind="adjacent", window=3),
                RefinementStrategy(kind="section", enabled=False),
            ],
        )
        assert len(ctx.refinement_strategies) == 2
        assert ctx.refinement_strategies[0].kind == "adjacent"
        assert ctx.refinement_strategies[0].window == 3
        assert ctx.refinement_strategies[1].enabled is False

    def test_rejects_extra_fields(self):
        with pytest.raises(ValidationError):
            SemanticContext(unknown="bad")
