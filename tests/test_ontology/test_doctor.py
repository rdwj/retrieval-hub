"""Tests for ontology doctor health-check functions."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from retrieval_hub.db.base import Base
from retrieval_hub.models.query_metrics import OntologyQueryMetric
from retrieval_hub.ontology.doctor import (
    check_dangling_relationships,
    check_duplicate_mappings,
    check_eval_findings,
    check_family_mismatches,
    check_low_hit_rate,
    check_missing_mappings,
    check_orphan_concepts,
    check_score_clustering,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_source(slug, status="curated", family="document", semantic_context=None):
    return SimpleNamespace(
        slug=slug, status=status, family=family,
        semantic_context=semantic_context,
    )


def _make_mapping(
    id, canonical_name, source_slug, local_name="Condition", authority_score=1.0,
):
    return SimpleNamespace(
        id=id, canonical_name=canonical_name, source_slug=source_slug,
        local_name=local_name, authority_score=authority_score,
    )


def _make_concept(name, parent_name=None):
    return SimpleNamespace(name=name, parent_name=parent_name)


def _make_relationship(id, source_concept, relationship, target_concept):
    return SimpleNamespace(
        id=id, source_concept=source_concept,
        relationship=relationship, target_concept=target_concept,
    )


class _MockQuery:
    """Chainable mock that supports the query patterns used by doctor checks."""

    def __init__(self, results):
        self._results = list(results)

    def filter(self, *args, **kwargs):
        return self

    def all(self):
        return self._results

    def first(self):
        return self._results[0] if self._results else None

    def distinct(self):
        return self

    def group_by(self, *args):
        return self

    def having(self, *args):
        return self

    def __iter__(self):
        return iter(self._results)


def _session_with_queries(*query_results):
    """Return a mock session that yields *query_results* in call order."""
    session = MagicMock()
    results = list(query_results)
    idx = [0]

    def _route(*args, **kw):
        q = _MockQuery(results[idx[0]])
        idx[0] += 1
        return q

    session.query.side_effect = _route
    return session


# ---------------------------------------------------------------------------
# check_missing_mappings
# ---------------------------------------------------------------------------


def test_missing_mappings_all_mapped():
    src = _make_source("s", semantic_context={
        "entities": [{"name": "Condition", "entity_type": "condition"}, {"name": "Medication", "entity_type": "treatment"}],
    })
    session = _session_with_queries(
        [src],
        [SimpleNamespace(local_name="Condition"), SimpleNamespace(local_name="Medication")],
    )
    assert check_missing_mappings(session) == []


def test_missing_mappings_partial():
    src = _make_source("s", semantic_context={
        "entities": [
            {"name": "Condition", "entity_type": "condition"},
            {"name": "Medication", "entity_type": "treatment"},
            {"name": "Procedure", "entity_type": "procedure"},
        ],
    })
    session = _session_with_queries(
        [src],
        [SimpleNamespace(local_name="Condition")],
    )
    findings = check_missing_mappings(session)
    assert len(findings) == 1
    assert findings[0]["severity"] == "WARN"
    assert findings[0]["unmapped"] == ["Medication", "Procedure"]
    assert findings[0]["mapped_count"] == 1


def test_missing_mappings_zero_mapped():
    src = _make_source("s", semantic_context={
        "entities": [{"name": "Condition", "entity_type": "condition"}],
    })
    session = _session_with_queries([src], [])
    findings = check_missing_mappings(session)
    assert len(findings) == 1
    assert findings[0]["severity"] == "INFO"


def test_missing_mappings_retired_excluded_by_default():
    src = _make_source("s", status="retired", semantic_context={
        "entities": [{"name": "Condition", "entity_type": "condition"}],
    })
    session = _session_with_queries([src])
    assert check_missing_mappings(session) == []


def test_missing_mappings_retired_included():
    src = _make_source("s", status="retired", semantic_context={
        "entities": [{"name": "Condition", "entity_type": "condition"}],
    })
    session = _session_with_queries([src], [])
    findings = check_missing_mappings(session, include_retired=True)
    assert len(findings) == 1


def test_missing_mappings_no_semantic_context():
    src = _make_source("s", semantic_context=None)
    session = _session_with_queries([src])
    assert check_missing_mappings(session) == []


def test_missing_mappings_source_slug_filter():
    src = _make_source("target", semantic_context={
        "entities": [{"name": "Condition", "entity_type": "condition"}],
    })
    session = _session_with_queries(
        [src],
        [SimpleNamespace(local_name="Condition")],
    )
    findings = check_missing_mappings(session, source_slug="target")
    assert findings == []
    first_call_args = session.query.call_args_list[0]
    assert first_call_args is not None


# ---------------------------------------------------------------------------
# check_duplicate_mappings
# ---------------------------------------------------------------------------


def test_duplicate_mappings_none():
    session = _session_with_queries([])
    assert check_duplicate_mappings(session) == []


def test_duplicate_mappings_found():
    dup_row = SimpleNamespace(source_slug="s", canonical_name="Condition", cnt=2)
    local_rows = [
        SimpleNamespace(local_name="condition"),
        SimpleNamespace(local_name="Conditions"),
    ]
    session = _session_with_queries(
        [(dup_row.source_slug, dup_row.canonical_name, dup_row.cnt)],
        local_rows,
    )
    findings = check_duplicate_mappings(session)
    assert len(findings) == 1
    assert findings[0]["canonical_name"] == "Condition"
    assert findings[0]["local_names"] == ["Conditions", "condition"]


# ---------------------------------------------------------------------------
# check_orphan_concepts
# ---------------------------------------------------------------------------


def test_orphan_concepts_none():
    mapped = [SimpleNamespace(canonical_name="Condition")]
    concepts = [_make_concept("Condition")]
    session = _session_with_queries(mapped, concepts)
    assert check_orphan_concepts(session) == []


def test_orphan_concepts_found():
    mapped = [SimpleNamespace(canonical_name="Condition")]
    concepts = [_make_concept("Condition"), _make_concept("Orphan", parent_name="root")]
    session = _session_with_queries(mapped, concepts)
    findings = check_orphan_concepts(session)
    assert len(findings) == 1
    assert findings[0]["concept_name"] == "Orphan"
    assert findings[0]["parent_name"] == "root"


# ---------------------------------------------------------------------------
# check_dangling_relationships
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "src_exists, tgt_exists, expected_end",
    [
        (False, True, "source"),
        (True, False, "target"),
        (False, False, "both"),
    ],
    ids=["dangling-source", "dangling-target", "dangling-both"],
)
def test_dangling_relationships(src_exists, tgt_exists, expected_end):
    concept_names = []
    if src_exists:
        concept_names.append(SimpleNamespace(name="A"))
    if tgt_exists:
        concept_names.append(SimpleNamespace(name="B"))
    rel = _make_relationship(1, "A", "treats", "B")

    session = _session_with_queries(concept_names, [rel])
    findings = check_dangling_relationships(session)
    assert len(findings) == 1
    assert findings[0]["dangling_end"] == expected_end


def test_dangling_relationships_none():
    concept_names = [SimpleNamespace(name="A"), SimpleNamespace(name="B")]
    rels = [_make_relationship(1, "A", "treats", "B")]
    session = _session_with_queries(concept_names, rels)
    assert check_dangling_relationships(session) == []


# ---------------------------------------------------------------------------
# check_family_mismatches
# ---------------------------------------------------------------------------


def test_family_mismatches_graph_only():
    sources = [_make_source("g1", family="graph"), _make_source("g2", family="graph")]
    mappings = [
        _make_mapping(1, "Condition", "g1"),
        _make_mapping(2, "Condition", "g2"),
    ]
    session = _session_with_queries(sources, mappings)
    assert check_family_mismatches(session) == []


def test_family_mismatches_mixed():
    sources = [
        _make_source("g", family="graph"),
        _make_source("d", family="document"),
    ]
    mappings = [
        _make_mapping(1, "Condition", "g"),
        _make_mapping(2, "Condition", "d"),
    ]
    session = _session_with_queries(sources, mappings)
    findings = check_family_mismatches(session)
    assert len(findings) == 1
    assert findings[0]["graph_sources"] == ["g"]
    assert findings[0]["document_sources"] == ["d"]


# ---------------------------------------------------------------------------
# check_score_clustering
# ---------------------------------------------------------------------------


def test_score_clustering_narrow_range():
    mappings = [
        _make_mapping(1, "A", "s1", authority_score=0.8),
        _make_mapping(2, "B", "s2", authority_score=0.9),
    ]
    session = _session_with_queries(mappings)
    findings = check_score_clustering(session)
    narrow = [f for f in findings if f["issue"] == "narrow_range"]
    assert len(narrow) == 1
    assert narrow[0]["spread"] == pytest.approx(0.1)


def test_score_clustering_wide_range():
    mappings = [
        _make_mapping(1, "A", "s1", authority_score=0.3),
        _make_mapping(2, "B", "s2", authority_score=0.9),
    ]
    session = _session_with_queries(mappings)
    findings = check_score_clustering(session)
    narrow = [f for f in findings if f["issue"] == "narrow_range"]
    assert narrow == []


def test_score_clustering_shared_max():
    mappings = [
        _make_mapping(1, "A", "s1", authority_score=1.0),
        _make_mapping(2, "B", "s2", authority_score=1.0),
        _make_mapping(3, "C", "s3", authority_score=0.5),
    ]
    session = _session_with_queries(mappings)
    findings = check_score_clustering(session)
    shared = [f for f in findings if f["issue"] == "shared_max"]
    assert len(shared) == 1
    assert sorted(shared[0]["concepts_at_max"]) == ["A", "B"]


def test_score_clustering_no_within_concept_diff():
    mappings = [
        _make_mapping(1, "A", "s1", authority_score=0.8),
        _make_mapping(2, "A", "s2", authority_score=0.8),
        _make_mapping(3, "B", "s3", authority_score=0.3),
    ]
    session = _session_with_queries(mappings)
    findings = check_score_clustering(session)
    no_diff = [f for f in findings if f["issue"] == "no_within_concept_diff"]
    assert len(no_diff) == 1
    assert no_diff[0]["canonical_name"] == "A"
    assert no_diff[0]["mapping_count"] == 2


def test_score_clustering_empty():
    session = _session_with_queries([])
    assert check_score_clustering(session) == []


# ---------------------------------------------------------------------------
# check_eval_findings
# ---------------------------------------------------------------------------


def test_check_eval_findings_dead():
    """Dead eval finding produces WARN."""
    session = MagicMock()
    findings_data = [{
        "category": "dead",
        "canonical_name": "Condition",
        "source_slug": "test-source",
        "local_name": "Disease",
        "metrics": {"is_dead": True, "total_hits": 0},
    }]
    results = check_eval_findings(session, eval_findings=findings_data)
    assert len(results) == 1
    assert results[0]["check"] == "eval_dead_mapping"
    assert results[0]["severity"] == "WARN"
    assert results[0]["canonical_name"] == "Condition"


def test_check_eval_findings_underperforming():
    """Underperforming eval finding produces INFO."""
    session = MagicMock()
    findings_data = [{
        "category": "underperforming",
        "canonical_name": "Compound",
        "source_slug": "test-source",
        "local_name": "Drug",
        "metrics": {"precision": 0.15, "total_hits": 3},
    }]
    results = check_eval_findings(session, eval_findings=findings_data)
    assert len(results) == 1
    assert results[0]["check"] == "eval_underperforming"
    assert results[0]["severity"] == "INFO"


def test_check_eval_findings_healthy_skipped():
    """Healthy eval findings are not reported."""
    session = MagicMock()
    findings_data = [{
        "category": "healthy",
        "canonical_name": "Condition",
        "source_slug": "test-source",
        "local_name": "Disease",
        "metrics": {"precision": 0.8},
    }]
    results = check_eval_findings(session, eval_findings=findings_data)
    assert len(results) == 0


def test_check_eval_findings_missing_coverage():
    """Missing coverage eval finding produces INFO."""
    session = MagicMock()
    findings_data = [{
        "category": "missing_coverage",
        "canonical_name": "Anatomy",
        "source_slug": "test-source",
        "local_name": "Body Structure",
        "metrics": {},
    }]
    results = check_eval_findings(session, eval_findings=findings_data)
    assert len(results) == 1
    assert results[0]["check"] == "eval_missing_coverage"
    assert results[0]["severity"] == "INFO"


def test_check_eval_findings_empty():
    """Empty findings list returns empty results."""
    session = MagicMock()
    results = check_eval_findings(session, eval_findings=[])
    assert results == []


# ---------------------------------------------------------------------------
# check_low_hit_rate
# ---------------------------------------------------------------------------


@pytest.fixture
def db_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    make_session = sessionmaker(bind=engine)
    session = make_session()
    yield session
    session.close()
    engine.dispose()


class TestCheckLowHitRate:
    def test_flags_low_hit_rate(self, db_session):
        """Mapping with zero hits is flagged."""
        now = datetime.now(UTC)
        for _ in range(5):
            db_session.add(OntologyQueryMetric(
                mapping_id=1, source_slug="src-a", canonical_name="Condition",
                hit_count=0, top_score=None, query_timestamp=now,
            ))
        db_session.flush()

        findings = check_low_hit_rate(db_session, threshold=0.1)
        assert len(findings) == 1
        assert findings[0]["check"] == "low_hit_rate"
        assert findings[0]["severity"] == "WARN"
        assert findings[0]["hit_rate"] == 0.0

    def test_healthy_mapping_not_flagged(self, db_session):
        """Mapping with high hit rate is not flagged."""
        now = datetime.now(UTC)
        for _ in range(10):
            db_session.add(OntologyQueryMetric(
                mapping_id=1, source_slug="src-a", canonical_name="Condition",
                hit_count=5, top_score=0.8, query_timestamp=now,
            ))
        db_session.flush()

        findings = check_low_hit_rate(db_session, threshold=0.1)
        assert len(findings) == 0

    def test_empty_metrics_returns_empty(self, db_session):
        """No metrics returns no findings."""
        findings = check_low_hit_rate(db_session)
        assert findings == []

    def test_respects_time_window(self, db_session):
        """Only considers metrics within the specified time window."""
        now = datetime.now(UTC)
        # Old metrics (outside window) - all zeros
        for _ in range(5):
            db_session.add(OntologyQueryMetric(
                mapping_id=1, source_slug="src-a", canonical_name="Condition",
                hit_count=0, top_score=None, query_timestamp=now - timedelta(days=10),
            ))
        # Recent metrics (within window) - all hits
        for _ in range(5):
            db_session.add(OntologyQueryMetric(
                mapping_id=1, source_slug="src-a", canonical_name="Condition",
                hit_count=5, top_score=0.8, query_timestamp=now,
            ))
        db_session.flush()

        findings = check_low_hit_rate(db_session, days=7, threshold=0.1)
        assert len(findings) == 0  # Only recent (healthy) metrics are considered
