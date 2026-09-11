"""Integration tests for ontology query monitoring with concept_query."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from retrieval_hub.models.ontology import OntologyMapping
from retrieval_hub.models.ontology_concept import OntologyConcept
from retrieval_hub.models.query_metrics import OntologyQueryMetric
from retrieval_hub.retrieval.api import ConceptNotMappedError, RetrievalResult, concept_query
from tests.conftest import make_physical_index, make_recipe_version, make_source


def _make_queryable_source(session, *, slug: str) -> None:
    """Create a source with an active physical index (queryable)."""
    src = make_source(session, slug=slug)
    rv = make_recipe_version(session, src)
    pi = make_physical_index(session, src, rv)
    src.active_physical_index_id = pi.id
    session.flush()


class TestConceptQueryMonitoring:
    """Test that concept_query() correctly records metrics."""

    def test_concept_query_records_metrics_on_success(self, session):
        """When concept_query succeeds, metrics are recorded for exercised mappings."""
        # Create queryable sources
        _make_queryable_source(session, slug="source-a")
        _make_queryable_source(session, slug="source-b")

        # Set up ontology data
        concept = OntologyConcept(name="Condition")
        session.add(concept)
        session.flush()

        m1 = OntologyMapping(
            canonical_name="Condition",
            source_slug="source-a",
            local_name="Disorder",
            authority_score=0.9,
        )
        m2 = OntologyMapping(
            canonical_name="Condition",
            source_slug="source-b",
            local_name="Disease",
            authority_score=0.8,
        )
        session.add_all([m1, m2])
        session.flush()

        # Mock the underlying query() function to return results
        mock_results_a = [
            RetrievalResult(
                chunk_id="chunk-1",
                text="test",
                score=0.95,
                doc_title="Doc A",
                doc_url="http://example.com/a",
                doc_section="Section",
                chunk_index=0,
                physical_index_id="idx-1",
                recipe_version=1,
                request_id="req-1",
                source_slug="source-a",
            ),
        ]
        mock_results_b = []

        with patch("retrieval_hub.retrieval.api.query") as mock_query:
            mock_query.side_effect = lambda slug, *args, **kwargs: (
                mock_results_a if slug == "source-a" else mock_results_b
            )

            # Call concept_query
            results, mappings = concept_query(
                "Condition",
                "test query",
                session=session,
                top_k=5,
            )

            # Verify metrics were recorded
            metrics = session.query(OntologyQueryMetric).all()
            assert len(metrics) == 2

            # Check source-a metrics
            metric_a = next(m for m in metrics if m.source_slug == "source-a")
            assert metric_a.mapping_id == m1.id
            assert metric_a.canonical_name == "Condition"
            assert metric_a.hit_count == 1
            assert metric_a.top_score == pytest.approx(0.95)

            # Check source-b metrics
            metric_b = next(m for m in metrics if m.source_slug == "source-b")
            assert metric_b.mapping_id == m2.id
            assert metric_b.canonical_name == "Condition"
            assert metric_b.hit_count == 0
            assert metric_b.top_score is None

    def test_concept_query_silent_on_monitoring_failure(self, session):
        """If monitoring fails, concept_query still returns results."""
        # Create queryable source
        _make_queryable_source(session, slug="source-a")

        concept = OntologyConcept(name="Condition")
        session.add(concept)
        session.flush()

        m1 = OntologyMapping(
            canonical_name="Condition",
            source_slug="source-a",
            local_name="Disorder",
            authority_score=0.9,
        )
        session.add(m1)
        session.flush()

        mock_results = [
            RetrievalResult(
                chunk_id="chunk-1",
                text="test",
                score=0.85,
                doc_title="Doc",
                doc_url="http://example.com",
                doc_section="Section",
                chunk_index=0,
                physical_index_id="idx-1",
                recipe_version=1,
                request_id="req-1",
                source_slug="source-a",
            ),
        ]

        with patch("retrieval_hub.retrieval.api.query") as mock_query:
            mock_query.return_value = mock_results

            # Patch record_query_metrics at its source to raise an exception
            with patch(
                "retrieval_hub.ontology.monitoring.record_query_metrics",
                side_effect=RuntimeError("DB connection lost"),
            ):
                # Should not raise, should return results
                results, mappings = concept_query(
                    "Condition",
                    "test query",
                    session=session,
                    top_k=5,
                )

                # Results are returned despite monitoring failure
                assert len(results) > 0
                assert "source-a" in mappings

    def test_concept_query_no_metrics_when_no_mappings(self, session):
        """When concept has no mappings, no metrics are recorded."""
        # No mappings in DB
        with pytest.raises(ConceptNotMappedError):
            concept_query(
                "UnknownConcept",
                "test query",
                session=session,
                top_k=5,
            )

        # No metrics should exist
        metrics = session.query(OntologyQueryMetric).all()
        assert len(metrics) == 0
