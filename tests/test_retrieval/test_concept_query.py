"""Tests for concept-first retrieval: resolve_concept_sources, concept_query, rrf_merge weights.

These tests exercise the concept-first retrieval path introduced for
ontology-driven fanout. ``resolve_concept_sources`` is tested against
the real SQLite DB; ``concept_query`` patches the underlying ``query()``
to avoid needing a vectors DB.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from retrieval_hub.models.ontology import OntologyMapping
from retrieval_hub.models.ontology_concept import OntologyConcept
from retrieval_hub.retrieval.api import (
    ConceptNotMappedError,
    RetrievalResult,
    SourceNotQueryableError,
    concept_query,
    resolve_concept_sources,
    rrf_merge,
)
from tests.conftest import make_physical_index, make_recipe_version, make_source

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_queryable_source(session, *, slug: str) -> None:
    """Create a source with an active physical index (queryable)."""
    src = make_source(session, slug=slug)
    rv = make_recipe_version(session, src)
    pi = make_physical_index(session, src, rv)
    src.active_physical_index_id = pi.id
    session.flush()


def _make_result(
    *,
    chunk_id: str = "c1",
    score: float = 0.9,
    source_slug: str = "src",
) -> RetrievalResult:
    """Build a minimal RetrievalResult for merge tests."""
    return RetrievalResult(
        chunk_id=chunk_id,
        text="text",
        score=score,
        doc_title="doc",
        doc_url="http://example.com",
        doc_section=None,
        chunk_index=0,
        physical_index_id="pi-1",
        recipe_version=1,
        request_id="req-1",
        source_slug=source_slug,
    )


# ---------------------------------------------------------------------------
# TestResolveConceptSources
# ---------------------------------------------------------------------------


class TestResolveConceptSources:
    """Tests for resolve_concept_sources against the real DB."""

    def test_basic_resolution(self, session):
        """Two mappings for 'Condition' in different sources both resolve."""
        _make_queryable_source(session, slug="source-a")
        _make_queryable_source(session, slug="source-b")
        session.add_all([
            OntologyMapping(
                canonical_name="Condition",
                source_slug="source-a",
                local_name="Disorder",
            ),
            OntologyMapping(
                canonical_name="Condition",
                source_slug="source-b",
                local_name="Condition",
            ),
        ])
        session.flush()

        result = resolve_concept_sources(session, "Condition")

        assert len(result) == 2
        slugs = {m.source_slug for m in result}
        assert slugs == {"source-a", "source-b"}
        # Check local_names are correct per source.
        by_slug = {m.source_slug: m for m in result}
        assert by_slug["source-a"].local_names == ["Disorder"]
        assert by_slug["source-b"].local_names == ["Condition"]

    def test_max_authority_weight(self, session):
        """When a source has multiple mappings, authority_weight is the max score."""
        _make_queryable_source(session, slug="source-a")
        session.add_all([
            OntologyMapping(
                canonical_name="Condition",
                source_slug="source-a",
                local_name="Disorder",
                authority_score=0.7,
            ),
            OntologyMapping(
                canonical_name="Condition",
                source_slug="source-a",
                local_name="Disease",
                authority_score=0.9,
            ),
        ])
        session.flush()

        result = resolve_concept_sources(session, "Condition")

        assert len(result) == 1
        assert result[0].authority_weight == pytest.approx(0.9)

    def test_hierarchy_expansion(self, session):
        """Hierarchy children of the queried concept are included."""
        _make_queryable_source(session, slug="source-a")
        _make_queryable_source(session, slug="source-b")
        session.add_all([
            OntologyConcept(name="Condition"),
            OntologyConcept(name="Hypertension", parent_name="Condition"),
        ])
        session.flush()
        session.add_all([
            OntologyMapping(
                canonical_name="Hypertension",
                source_slug="source-a",
                local_name="HTN",
            ),
            OntologyMapping(
                canonical_name="Condition",
                source_slug="source-b",
                local_name="Condition",
            ),
        ])
        session.flush()

        result = resolve_concept_sources(session, "Condition")

        slugs = {m.source_slug for m in result}
        assert "source-a" in slugs, "source-a should be found via hierarchy child"
        assert "source-b" in slugs, "source-b should be found via direct match"

    def test_no_hierarchy_expansion(self, session):
        """With expand_hierarchy=False, only direct matches are returned."""
        _make_queryable_source(session, slug="source-a")
        _make_queryable_source(session, slug="source-b")
        session.add_all([
            OntologyConcept(name="Condition"),
            OntologyConcept(name="Hypertension", parent_name="Condition"),
        ])
        session.flush()
        session.add_all([
            OntologyMapping(
                canonical_name="Hypertension",
                source_slug="source-a",
                local_name="HTN",
            ),
            OntologyMapping(
                canonical_name="Condition",
                source_slug="source-b",
                local_name="Condition",
            ),
        ])
        session.flush()

        result = resolve_concept_sources(
            session, "Condition", expand_hierarchy=False,
        )

        slugs = {m.source_slug for m in result}
        assert "source-b" in slugs, "Direct match should still be found"
        assert "source-a" not in slugs, "Hierarchy child should be excluded"

    def test_filters_unqueryable_sources(self, session):
        """Sources without an active physical index are excluded."""
        # Source with no active_physical_index_id (not queryable).
        make_source(session, slug="inactive-source")
        session.add(
            OntologyMapping(
                canonical_name="Condition",
                source_slug="inactive-source",
                local_name="Disorder",
            ),
        )
        session.flush()

        result = resolve_concept_sources(session, "Condition")

        assert result == []

    def test_case_insensitive(self, session):
        """Concept lookup is case-insensitive."""
        _make_queryable_source(session, slug="source-a")
        session.add(
            OntologyMapping(
                canonical_name="Condition",
                source_slug="source-a",
                local_name="Disorder",
            ),
        )
        session.flush()

        result = resolve_concept_sources(session, "condition")

        assert len(result) == 1
        assert result[0].source_slug == "source-a"

    def test_empty_result(self, session):
        """Unknown concept returns an empty list."""
        result = resolve_concept_sources(session, "Nonexistent")
        assert result == []

    def test_sorted_by_authority_weight(self, session):
        """Results are sorted by authority_weight descending."""
        for slug, score in [("lo", 0.7), ("hi", 0.9), ("mid", 0.8)]:
            _make_queryable_source(session, slug=slug)
            session.add(
                OntologyMapping(
                    canonical_name="Condition",
                    source_slug=slug,
                    local_name="Disorder",
                    authority_score=score,
                ),
            )
        session.flush()

        result = resolve_concept_sources(session, "Condition")

        weights = [m.authority_weight for m in result]
        assert weights == sorted(weights, reverse=True)
        assert weights == [pytest.approx(0.9), pytest.approx(0.8), pytest.approx(0.7)]


# ---------------------------------------------------------------------------
# TestConceptQuery
# ---------------------------------------------------------------------------


class TestConceptQuery:
    """Tests for concept_query with a mocked query() backend."""

    def test_fans_out_with_correct_doc_sections(self, session):
        """Each source is queried with its own local_names as doc_section."""
        _make_queryable_source(session, slug="source-a")
        _make_queryable_source(session, slug="source-b")
        session.add_all([
            OntologyMapping(
                canonical_name="Condition",
                source_slug="source-a",
                local_name="Disorder",
            ),
            OntologyMapping(
                canonical_name="Condition",
                source_slug="source-b",
                local_name="Condition",
            ),
        ])
        session.flush()

        with patch("retrieval_hub.retrieval.api.query", return_value=[]) as mock_q:
            concept_query(
                "Condition",
                "What is hypertension?",
                session=session,
            )

        assert mock_q.call_count == 2
        # concept_query passes local_names as doc_section; check positional arg [0] for slug.
        for call in mock_q.call_args_list:
            slug = call.args[0]
            doc_section = call.kwargs.get("doc_section")
            if slug == "source-a":
                assert doc_section == ["Disorder"]
            elif slug == "source-b":
                assert doc_section == ["Condition"]

    def test_authority_weighting_affects_ordering(self, session):
        """Higher authority weight produces higher RRF scores."""
        _make_queryable_source(session, slug="low-auth")
        _make_queryable_source(session, slug="high-auth")
        session.add_all([
            OntologyMapping(
                canonical_name="Condition",
                source_slug="low-auth",
                local_name="Disorder",
                authority_score=0.6,
            ),
            OntologyMapping(
                canonical_name="Condition",
                source_slug="high-auth",
                local_name="Condition",
                authority_score=0.9,
            ),
        ])
        session.flush()

        def fake_query(source_slug, *args, **kwargs):
            return [
                _make_result(chunk_id=f"hit-{source_slug}", source_slug=source_slug),
            ]

        with patch("retrieval_hub.retrieval.api.query", side_effect=fake_query):
            results, mappings = concept_query(
                "Condition",
                "What is hypertension?",
                session=session,
            )

        assert len(results) == 2
        # The first result should be from the higher-authority source.
        assert results[0].source_slug == "high-auth"
        assert results[0].score > results[1].score

    def test_raises_concept_not_mapped_error(self, session):
        """ConceptNotMappedError when no sources map to the concept."""
        with pytest.raises(ConceptNotMappedError, match="Nonexistent"):
            concept_query(
                "Nonexistent",
                "anything",
                session=session,
            )

    def test_skips_unqueryable_source(self, session):
        """Sources that raise SourceNotQueryableError are silently skipped."""
        _make_queryable_source(session, slug="good-source")
        _make_queryable_source(session, slug="bad-source")
        session.add_all([
            OntologyMapping(
                canonical_name="Condition",
                source_slug="good-source",
                local_name="Disorder",
            ),
            OntologyMapping(
                canonical_name="Condition",
                source_slug="bad-source",
                local_name="Condition",
            ),
        ])
        session.flush()

        def selective_query(source_slug, *args, **kwargs):
            if source_slug == "bad-source":
                raise SourceNotQueryableError(f"{source_slug} is down")
            return [_make_result(chunk_id="good-hit", source_slug=source_slug)]

        with patch("retrieval_hub.retrieval.api.query", side_effect=selective_query):
            results, mappings = concept_query(
                "Condition",
                "What is hypertension?",
                session=session,
            )

        assert len(results) == 1
        assert results[0].source_slug == "good-source"


# ---------------------------------------------------------------------------
# TestRrfMergeWithWeights
# ---------------------------------------------------------------------------


class TestRrfMergeWithWeights:
    """Tests for rrf_merge with the source_weights parameter."""

    def test_source_weights_multiply_scores(self):
        """source_weights scale the RRF score per source."""
        per_source = {
            "a": [_make_result(chunk_id="a1", source_slug="a")],
            "b": [_make_result(chunk_id="b1", source_slug="b")],
        }

        merged = rrf_merge(
            per_source,
            source_weights={"a": 2.0, "b": 0.5},
            top_k=10,
        )

        scores_by_slug = {r.source_slug: r.score for r in merged}
        # Both hits are rank 1, so base RRF = 1/(60+1). Weights scale that.
        base = 1.0 / (60 + 1)
        assert scores_by_slug["a"] == pytest.approx(base * 2.0)
        assert scores_by_slug["b"] == pytest.approx(base * 0.5)

    def test_no_weights_backward_compatible(self):
        """Without source_weights, all sources get weight 1.0."""
        per_source = {
            "a": [_make_result(chunk_id="a1", source_slug="a")],
            "b": [_make_result(chunk_id="b1", source_slug="b")],
        }

        merged_default = rrf_merge(per_source, top_k=10)
        merged_explicit = rrf_merge(
            per_source,
            source_weights={"a": 1.0, "b": 1.0},
            top_k=10,
        )

        default_scores = {r.source_slug: r.score for r in merged_default}
        explicit_scores = {r.source_slug: r.score for r in merged_explicit}
        assert default_scores == explicit_scores
