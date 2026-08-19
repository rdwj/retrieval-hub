"""Tests for rewriter output schemas: RewrittenQuery and RewriteResult."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from retrieval_hub.rewriter.schemas import RewriteResult, RewrittenQuery


class TestRewrittenQuery:
    """Validation rules for a single LLM-produced query variant."""

    def test_valid_construction(self) -> None:
        q = RewrittenQuery(
            text="postprandial hyperglycemia management",
            intent="blood sugar after eating",
            rationale="maps lay term to canonical",
            confidence=0.92,
        )
        assert q.text == "postprandial hyperglycemia management"
        assert q.intent == "blood sugar after eating"
        assert q.confidence == 0.92

    @pytest.mark.parametrize("bad_confidence", [-0.01, -1.0, 1.01, 2.0])
    def test_confidence_out_of_range_rejected(self, bad_confidence: float) -> None:
        with pytest.raises(ValidationError, match="confidence"):
            RewrittenQuery(
                text="q",
                intent="i",
                rationale="r",
                confidence=bad_confidence,
            )

    @pytest.mark.parametrize("edge", [0.0, 1.0])
    def test_confidence_boundary_values_accepted(self, edge: float) -> None:
        q = RewrittenQuery(text="q", intent="i", rationale="r", confidence=edge)
        assert q.confidence == edge

    def test_extra_fields_rejected(self) -> None:
        with pytest.raises(ValidationError, match="extra"):
            RewrittenQuery.model_validate(
                {
                    "text": "q",
                    "intent": "i",
                    "rationale": "r",
                    "confidence": 0.5,
                    "unexpected_field": True,
                }
            )

    def test_missing_required_field_rejected(self) -> None:
        with pytest.raises(ValidationError):
            RewrittenQuery(text="q", intent="i", confidence=0.5)  # type: ignore[call-arg]


class TestRewriteResult:
    """Validation rules for the complete rewrite operation result."""

    def _make_query(self, **overrides: object) -> RewrittenQuery:
        defaults = {
            "text": "rewritten",
            "intent": "test",
            "rationale": "reason",
            "confidence": 0.9,
        }
        defaults.update(overrides)
        return RewrittenQuery(**defaults)  # type: ignore[arg-type]

    def test_valid_construction(self) -> None:
        result = RewriteResult(
            queries=[self._make_query()],
            raw_query="original query",
            template_version="1",
            metadata_version="2024-01",
            llm="granite-3.3-8b",
            request_id="req-001",
        )
        assert len(result.queries) == 1
        assert result.raw_query == "original query"
        assert result.template_version == "1"
        assert result.metadata_version == "2024-01"
        assert result.llm == "granite-3.3-8b"

    def test_metadata_version_defaults_to_none(self) -> None:
        result = RewriteResult(
            queries=[],
            raw_query="q",
            template_version="1",
            llm="m",
            request_id="r",
        )
        assert result.metadata_version is None

    def test_extra_fields_rejected(self) -> None:
        with pytest.raises(ValidationError, match="extra"):
            RewriteResult.model_validate(
                {
                    "queries": [],
                    "raw_query": "q",
                    "template_version": "1",
                    "llm": "m",
                    "request_id": "r",
                    "bogus": True,
                }
            )

    def test_empty_queries_list_accepted(self) -> None:
        result = RewriteResult(
            queries=[],
            raw_query="q",
            template_version="1",
            llm="m",
            request_id="r",
        )
        assert result.queries == []
