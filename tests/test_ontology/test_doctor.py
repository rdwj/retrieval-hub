"""Tests for ontology doctor health-check functions."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from retrieval_hub.ontology.doctor import (
    check_dangling_relationships,
    check_duplicate_mappings,
    check_family_mismatches,
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
        "entities": [{"entity_type": "Condition"}, {"entity_type": "Medication"}],
    })
    session = _session_with_queries(
        [src],
        [SimpleNamespace(local_name="Condition"), SimpleNamespace(local_name="Medication")],
    )
    assert check_missing_mappings(session) == []


def test_missing_mappings_partial():
    src = _make_source("s", semantic_context={
        "entities": [
            {"entity_type": "Condition"},
            {"entity_type": "Medication"},
            {"entity_type": "Procedure"},
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
        "entities": [{"entity_type": "Condition"}],
    })
    session = _session_with_queries([src], [])
    findings = check_missing_mappings(session)
    assert len(findings) == 1
    assert findings[0]["severity"] == "INFO"


def test_missing_mappings_retired_excluded_by_default():
    src = _make_source("s", status="retired", semantic_context={
        "entities": [{"entity_type": "Condition"}],
    })
    session = _session_with_queries([src])
    assert check_missing_mappings(session) == []


def test_missing_mappings_retired_included():
    src = _make_source("s", status="retired", semantic_context={
        "entities": [{"entity_type": "Condition"}],
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
        "entities": [{"entity_type": "Condition"}],
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
