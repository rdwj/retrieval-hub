"""Tests for ontology query monitoring."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from retrieval_hub.db.base import Base
from retrieval_hub.models.ontology import OntologyMapping
from retrieval_hub.models.query_metrics import OntologyQueryMetric
from retrieval_hub.ontology.monitoring import get_mapping_hit_rates, record_query_metrics
from retrieval_hub.retrieval.api import ConceptSourceMapping, RetrievalResult


@pytest.fixture
def db_session():
    """In-memory SQLite session with ontology tables."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    make_session = sessionmaker(bind=engine)
    session = make_session()
    yield session
    session.close()
    engine.dispose()


def _make_retrieval_result(score=0.8, source_slug="src-a"):
    return RetrievalResult(
        chunk_id="chunk-1",
        text="test text",
        score=score,
        doc_title="Test Doc",
        doc_url="http://example.com",
        doc_section="Section",
        chunk_index=0,
        physical_index_id="idx-1",
        recipe_version=1,
        request_id="req-1",
        source_slug=source_slug,
    )


class TestRecordQueryMetrics:
    def test_records_metrics_for_exercised_mappings(self, db_session):
        """Records one metric row per mapping row exercised."""
        # Create mapping rows
        m1 = OntologyMapping(
            canonical_name="Condition", source_slug="src-a", local_name="Hypertension",
            authority_score=0.8,
        )
        m2 = OntologyMapping(
            canonical_name="Condition", source_slug="src-b", local_name="Disorder",
            authority_score=0.7,
        )
        db_session.add_all([m1, m2])
        db_session.flush()

        mappings_dict = {
            "src-a": ConceptSourceMapping(source_slug="src-a", local_names=["Hypertension"], authority_weight=0.8),
            "src-b": ConceptSourceMapping(source_slug="src-b", local_names=["Disorder"], authority_weight=0.7),
        }
        per_source = {
            "src-a": [_make_retrieval_result(0.9, "src-a"), _make_retrieval_result(0.7, "src-a")],
            "src-b": [],
        }

        count = record_query_metrics(db_session, "Condition", mappings_dict, per_source)

        assert count == 2
        metrics = db_session.query(OntologyQueryMetric).all()
        assert len(metrics) == 2

        # src-a had 2 hits
        metric_a = next(m for m in metrics if m.source_slug == "src-a")
        assert metric_a.hit_count == 2
        assert metric_a.top_score == pytest.approx(0.9)
        assert metric_a.canonical_name == "Condition"

        # src-b had 0 hits
        metric_b = next(m for m in metrics if m.source_slug == "src-b")
        assert metric_b.hit_count == 0
        assert metric_b.top_score is None

    def test_empty_mappings_returns_zero(self, db_session):
        """Empty mappings dict produces no metrics."""
        count = record_query_metrics(db_session, "Condition", {}, {})
        assert count == 0

    def test_no_matching_db_rows_skips(self, db_session):
        """Mappings without matching DB rows are skipped."""
        mappings_dict = {
            "src-x": ConceptSourceMapping(source_slug="src-x", local_names=["X"], authority_weight=0.5),
        }
        per_source = {"src-x": [_make_retrieval_result(0.5, "src-x")]}

        count = record_query_metrics(db_session, "Condition", mappings_dict, per_source)
        assert count == 0

    def test_multiple_mappings_per_source(self, db_session):
        """Multiple mapping rows for same source each get a metric."""
        m1 = OntologyMapping(
            canonical_name="Condition", source_slug="src-a", local_name="Hypertension",
            authority_score=0.8,
        )
        m2 = OntologyMapping(
            canonical_name="Condition", source_slug="src-a", local_name="Blood Pressure",
            authority_score=0.8,
        )
        db_session.add_all([m1, m2])
        db_session.flush()

        mappings_dict = {
            "src-a": ConceptSourceMapping(source_slug="src-a", local_names=["Hypertension", "Blood Pressure"], authority_weight=0.8),
        }
        per_source = {"src-a": [_make_retrieval_result(0.85, "src-a")]}

        count = record_query_metrics(db_session, "Condition", mappings_dict, per_source)
        assert count == 2


class TestGetMappingHitRates:
    def test_computes_hit_rates(self, db_session):
        """Hit rate is computed correctly from recorded metrics."""
        now = datetime.now(UTC)
        # 3 queries: 2 with hits, 1 without
        for i in range(3):
            db_session.add(OntologyQueryMetric(
                mapping_id=1, source_slug="src-a", canonical_name="Condition",
                hit_count=5 if i < 2 else 0,
                top_score=0.8 if i < 2 else None,
                query_timestamp=now - timedelta(hours=i),
            ))
        db_session.flush()

        rates = get_mapping_hit_rates(db_session, days=7)
        assert len(rates) == 1
        assert rates[0]["total_queries"] == 3
        assert rates[0]["hit_queries"] == 2
        assert rates[0]["hit_rate"] == pytest.approx(0.667)

    def test_filters_by_time_window(self, db_session):
        """Only metrics within the time window are included."""
        now = datetime.now(UTC)
        # Recent metric (within window)
        db_session.add(OntologyQueryMetric(
            mapping_id=1, source_slug="src-a", canonical_name="Condition",
            hit_count=5, top_score=0.8, query_timestamp=now,
        ))
        # Old metric (outside 7-day window)
        db_session.add(OntologyQueryMetric(
            mapping_id=1, source_slug="src-a", canonical_name="Condition",
            hit_count=5, top_score=0.8, query_timestamp=now - timedelta(days=10),
        ))
        db_session.flush()

        rates = get_mapping_hit_rates(db_session, days=7)
        assert len(rates) == 1
        assert rates[0]["total_queries"] == 1

    def test_filters_by_source_slug(self, db_session):
        """source_slug parameter filters results."""
        now = datetime.now(UTC)
        db_session.add(OntologyQueryMetric(
            mapping_id=1, source_slug="src-a", canonical_name="Condition",
            hit_count=5, top_score=0.8, query_timestamp=now,
        ))
        db_session.add(OntologyQueryMetric(
            mapping_id=2, source_slug="src-b", canonical_name="Condition",
            hit_count=3, top_score=0.7, query_timestamp=now,
        ))
        db_session.flush()

        rates = get_mapping_hit_rates(db_session, source_slug="src-a")
        assert len(rates) == 1
        assert rates[0]["source_slug"] == "src-a"

    def test_empty_table_returns_empty(self, db_session):
        """No metrics returns empty list."""
        rates = get_mapping_hit_rates(db_session)
        assert rates == []
