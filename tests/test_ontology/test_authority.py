"""Tests for ontology authority scoring heuristics."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from retrieval_hub.ontology.authority import (
    DEFAULT_FAMILY_WEIGHT,
    DEFAULT_STATUS_WEIGHT,
    _agreement_bonus,
    compute_authority_scores,
)


def _make_mapping(id, canonical_name, source_slug, authority_score=1.0):
    return SimpleNamespace(
        id=id,
        canonical_name=canonical_name,
        source_slug=source_slug,
        authority_score=authority_score,
    )


def _make_source(slug, status="curated", family="document", semantic_context=None):
    return SimpleNamespace(
        slug=slug,
        status=status,
        family=family,
        semantic_context=semantic_context,
    )


class _MockQuery:
    def __init__(self, results):
        self._results = results

    def filter(self, *args, **kwargs):
        return self

    def all(self):
        return self._results


# ---------------------------------------------------------------------------
# _agreement_bonus
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "num_sources, expected",
    [
        (1, 1.0),
        (2, 1.1),
        (3, 1.2),
        (4, 1.3),
        (5, 1.3),  # capped
    ],
)
def test_agreement_bonus(num_sources, expected):
    assert _agreement_bonus(num_sources) == pytest.approx(expected)


# ---------------------------------------------------------------------------
# compute_authority_scores — status weight
# ---------------------------------------------------------------------------


def test_published_scores_higher_than_curated():
    """Published source mappings score higher than curated ones."""
    mappings = [
        _make_mapping(1, "Condition", "src-pub"),
        _make_mapping(2, "Condition", "src-cur"),
    ]
    sources = [
        _make_source("src-pub", status="published", family="document"),
        _make_source("src-cur", status="curated", family="document"),
    ]

    session = MagicMock()

    def mock_query(model):
        if model.__tablename__ == "ontology_mapping":
            return _MockQuery(mappings)
        return _MockQuery(sources)

    session.query.side_effect = mock_query

    scores = dict(compute_authority_scores(session))
    assert scores[1] > scores[2]


def test_curated_scores_higher_than_draft():
    """Curated source mappings score higher than draft ones."""
    mappings = [
        _make_mapping(1, "Condition", "src-cur"),
        _make_mapping(2, "Condition", "src-draft"),
    ]
    sources = [
        _make_source("src-cur", status="curated", family="document"),
        _make_source("src-draft", status="draft", family="document"),
    ]

    session = MagicMock()

    def mock_query(model):
        if model.__tablename__ == "ontology_mapping":
            return _MockQuery(mappings)
        return _MockQuery(sources)

    session.query.side_effect = mock_query

    scores = dict(compute_authority_scores(session))
    assert scores[1] > scores[2]


# ---------------------------------------------------------------------------
# compute_authority_scores — family weight
# ---------------------------------------------------------------------------


def test_graph_scores_higher_than_document():
    """Graph-family sources score higher than document-family sources."""
    mappings = [
        _make_mapping(1, "Condition", "graph-src"),
        _make_mapping(2, "Condition", "doc-src"),
    ]
    sources = [
        _make_source("graph-src", family="graph"),
        _make_source("doc-src", family="document"),
    ]

    session = MagicMock()

    def mock_query(model):
        if model.__tablename__ == "ontology_mapping":
            return _MockQuery(mappings)
        return _MockQuery(sources)

    session.query.side_effect = mock_query

    scores = dict(compute_authority_scores(session))
    assert scores[1] > scores[2]


def test_clinical_document_scores_higher_than_document():
    """Clinical document sources score higher than general documents."""
    mappings = [
        _make_mapping(1, "Condition", "clin-src"),
        _make_mapping(2, "Condition", "doc-src"),
    ]
    sources = [
        _make_source("clin-src", family="clinical_document"),
        _make_source("doc-src", family="document"),
    ]

    session = MagicMock()

    def mock_query(model):
        if model.__tablename__ == "ontology_mapping":
            return _MockQuery(mappings)
        return _MockQuery(sources)

    session.query.side_effect = mock_query

    scores = dict(compute_authority_scores(session))
    assert scores[1] > scores[2]


# ---------------------------------------------------------------------------
# compute_authority_scores — agreement bonus
# ---------------------------------------------------------------------------


def test_multi_source_concept_scores_higher():
    """Mappings for concepts with more cross-source agreement score higher."""
    # "Condition" mapped by 3 sources, "Unique" mapped by 1
    mappings = [
        _make_mapping(1, "Condition", "src-a"),
        _make_mapping(2, "Condition", "src-b"),
        _make_mapping(3, "Condition", "src-c"),
        _make_mapping(4, "Unique", "src-a"),
    ]
    sources = [
        _make_source("src-a", family="document"),
        _make_source("src-b", family="document"),
        _make_source("src-c", family="document"),
    ]

    session = MagicMock()

    def mock_query(model):
        if model.__tablename__ == "ontology_mapping":
            return _MockQuery(mappings)
        return _MockQuery(sources)

    session.query.side_effect = mock_query

    scores = dict(compute_authority_scores(session))
    # All three "Condition" mappings should score higher than "Unique"
    assert scores[1] > scores[4]
    assert scores[2] > scores[4]
    assert scores[3] > scores[4]


# ---------------------------------------------------------------------------
# compute_authority_scores — explicit authority_weight override
# ---------------------------------------------------------------------------


def test_explicit_authority_weight_overrides_family():
    """semantic_context.authority_weight overrides the family-based weight."""
    mappings = [
        _make_mapping(1, "Condition", "custom-src"),
        _make_mapping(2, "Condition", "graph-src"),
    ]
    sources = [
        _make_source(
            "custom-src", family="document",
            semantic_context={"authority_weight": 2.0},
        ),
        _make_source("graph-src", family="graph"),
    ]

    session = MagicMock()

    def mock_query(model):
        if model.__tablename__ == "ontology_mapping":
            return _MockQuery(mappings)
        return _MockQuery(sources)

    session.query.side_effect = mock_query

    scores = dict(compute_authority_scores(session))
    # custom-src with explicit weight 2.0 should beat graph (1.3)
    assert scores[1] > scores[2]


# ---------------------------------------------------------------------------
# compute_authority_scores — edge cases
# ---------------------------------------------------------------------------


def test_missing_source_uses_defaults():
    """When source record is missing, default weights are used."""
    mappings = [_make_mapping(1, "Orphan", "missing-src")]

    session = MagicMock()

    def mock_query(model):
        if model.__tablename__ == "ontology_mapping":
            return _MockQuery(mappings)
        return _MockQuery([])  # no sources found

    session.query.side_effect = mock_query

    scores = dict(compute_authority_scores(session))
    expected = round(DEFAULT_STATUS_WEIGHT * DEFAULT_FAMILY_WEIGHT * 1.0, 3)
    assert scores[1] == pytest.approx(expected)


def test_empty_mappings_returns_empty():
    """No mappings returns an empty list."""
    session = MagicMock()

    def mock_query(model):
        return _MockQuery([])

    session.query.side_effect = mock_query

    assert compute_authority_scores(session) == []


def test_scores_are_rounded():
    """Scores are rounded to 3 decimal places."""
    mappings = [_make_mapping(1, "Concept", "src")]
    sources = [_make_source("src", status="curated", family="graph")]

    session = MagicMock()

    def mock_query(model):
        if model.__tablename__ == "ontology_mapping":
            return _MockQuery(mappings)
        return _MockQuery(sources)

    session.query.side_effect = mock_query

    scores = dict(compute_authority_scores(session))
    score_str = f"{scores[1]:.3f}"
    assert scores[1] == float(score_str)
