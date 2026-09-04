"""Tests for _resolve_embedding_endpoint in retrieval.api.

These tests exercise the registry-aware endpoint resolution introduced in
Phase 3. They use a real (SQLite) DB session so that ``resolve_model``
queries the model_endpoint table, while the RecipeVersion objects are
detached ORM instances whose ``.content`` is read in-process only.
"""

from __future__ import annotations

import pytest

from retrieval_hub.model_registry import ModelUnavailableError
from retrieval_hub.models import RecipeVersion
from retrieval_hub.retrieval.api import (
    RetrievalResult,
    SourceNotQueryableError,
    _resolve_embedding_endpoint,
    multi_query,
    rrf_merge,
)
from tests.conftest import make_model_endpoint


def _make_recipe_version(content: dict) -> RecipeVersion:
    """Build a detached RecipeVersion with the given content dict."""
    return RecipeVersion(
        id="rv1",
        source_id="s1",
        version_number=1,
        content=content,
    )


def test_resolve_embedding_endpoint_from_registry(session):
    """When model is in registry, returns registry endpoint URL."""
    make_model_endpoint(
        session,
        model_name="test/embed-v1",
        endpoint_url="http://registry:8000",
    )
    session.commit()

    rv = _make_recipe_version(
        {"embedding": {"model": "test/embed-v1", "endpoint": "http://recipe:9000"}}
    )
    url = _resolve_embedding_endpoint(session, rv)
    assert url == "http://registry:8000"


def test_resolve_embedding_endpoint_fallback_to_recipe(session):
    """When model is NOT in registry but recipe has endpoint, returns recipe endpoint."""
    rv = _make_recipe_version(
        {"embedding": {"model": "unregistered/model", "endpoint": "http://recipe:9000"}}
    )
    url = _resolve_embedding_endpoint(session, rv)
    assert url == "http://recipe:9000"


def test_resolve_embedding_endpoint_no_registry_no_recipe(session):
    """When model is NOT in registry and recipe has no endpoint, returns None."""
    rv = _make_recipe_version(
        {"embedding": {"model": "unregistered/model"}}
    )
    url = _resolve_embedding_endpoint(session, rv)
    assert url is None


def test_resolve_embedding_endpoint_no_model_in_recipe(session):
    """When recipe has no embedding.model, returns None."""
    rv = _make_recipe_version({"chunker": {"size": 512}})
    url = _resolve_embedding_endpoint(session, rv)
    assert url is None


def test_resolve_embedding_endpoint_unhealthy_model(session):
    """When model is unhealthy, raises ModelUnavailableError (not caught)."""
    make_model_endpoint(
        session,
        model_name="test/embed-v1",
        endpoint_url="http://registry:8000",
        status="unhealthy",
    )
    session.commit()

    rv = _make_recipe_version(
        {"embedding": {"model": "test/embed-v1"}}
    )
    url = _resolve_embedding_endpoint(session, rv)
    assert url == "http://registry:8000"


# ---------------------------------------------------------------------------
# rrf_merge
# ---------------------------------------------------------------------------


def _make_result(
    chunk_id="c1",
    text="text",
    score=0.9,
    doc_title="Doc",
    doc_url="https://example.com",
    doc_section=None,
    chunk_index=0,
    physical_index_id="pi-1",
    recipe_version=1,
    request_id="req-1",
    source_slug="",
) -> RetrievalResult:
    return RetrievalResult(
        chunk_id=chunk_id,
        text=text,
        score=score,
        doc_title=doc_title,
        doc_url=doc_url,
        doc_section=doc_section,
        chunk_index=chunk_index,
        physical_index_id=physical_index_id,
        recipe_version=recipe_version,
        request_id=request_id,
        source_slug=source_slug,
    )


def test_rrf_merge_two_sources():
    """RRF merge produces correct scores from two ranked lists."""
    source_a = [
        _make_result(chunk_id="a1", score=0.95, source_slug="src-a"),
        _make_result(chunk_id="a2", score=0.80, source_slug="src-a"),
    ]
    source_b = [
        _make_result(chunk_id="b1", score=0.90, source_slug="src-b"),
    ]

    merged = rrf_merge({"src-a": source_a, "src-b": source_b}, top_k=10)

    # Expected RRF scores with k=60:
    # a1: rank 1 -> 1/61 ≈ 0.01639
    # a2: rank 2 -> 1/62 ≈ 0.01613
    # b1: rank 1 -> 1/61 ≈ 0.01639
    assert len(merged) == 3
    # a1 and b1 are tied at rank 1 — both get 1/61
    assert merged[0].score == pytest.approx(1 / 61)
    assert merged[1].score == pytest.approx(1 / 61)
    assert merged[2].score == pytest.approx(1 / 62)
    assert merged[2].chunk_id == "a2"


def test_rrf_merge_single_source():
    """RRF merge with one source produces monotonically decreasing scores."""
    results = [
        _make_result(chunk_id="c1", score=0.95),
        _make_result(chunk_id="c2", score=0.80),
        _make_result(chunk_id="c3", score=0.70),
    ]

    merged = rrf_merge({"only": results}, top_k=10)

    assert len(merged) == 3
    assert merged[0].score > merged[1].score > merged[2].score
    assert merged[0].source_slug == "only"


def test_rrf_merge_respects_top_k():
    """RRF merge returns at most top_k results."""
    results = {
        "a": [_make_result(chunk_id=f"a{i}", score=1 - i * 0.1) for i in range(5)],
        "b": [_make_result(chunk_id=f"b{i}", score=1 - i * 0.1) for i in range(5)],
    }

    merged = rrf_merge(results, top_k=3)
    assert len(merged) == 3


def test_rrf_merge_empty_source():
    """A source with no results doesn't break the merge."""
    source_a = [_make_result(chunk_id="a1", score=0.9)]

    merged = rrf_merge({"a": source_a, "empty": []}, top_k=10)

    assert len(merged) == 1
    assert merged[0].chunk_id == "a1"


def test_rrf_merge_sets_source_slug():
    """RRF merge stamps source_slug on each result."""
    merged = rrf_merge(
        {
            "alpha": [_make_result(chunk_id="a1")],
            "beta": [_make_result(chunk_id="b1")],
        },
        top_k=10,
    )

    slugs = {r.source_slug for r in merged}
    assert slugs == {"alpha", "beta"}


# ---------------------------------------------------------------------------
# multi_query
# ---------------------------------------------------------------------------


def test_multi_query_routes_per_source(session):
    """multi_query calls query() once per slug and returns per-source results."""
    from unittest.mock import patch

    def mock_query(
        source_slug, query_text, *, session, top_k, vectors_db_url=None, request_id=None,
        doc_section=None, scope_entity_id=None,
    ):
        return [_make_result(chunk_id=f"{source_slug}-hit", source_slug=source_slug)]

    with patch("retrieval_hub.retrieval.api.query", side_effect=mock_query) as mock_q:
        results = multi_query(
            ["src-a", "src-b"],
            "test query",
            session=session,
            top_k=5,
        )

    assert set(results.keys()) == {"src-a", "src-b"}
    assert results["src-a"][0].chunk_id == "src-a-hit"
    assert results["src-b"][0].chunk_id == "src-b-hit"
    assert mock_q.call_count == 2


def test_multi_query_skips_unqueryable(session):
    """multi_query logs and skips sources that raise SourceNotQueryableError."""
    from unittest.mock import patch

    def mock_query(
        source_slug, query_text, *, session, top_k, vectors_db_url=None, request_id=None,
        doc_section=None, scope_entity_id=None,
    ):
        if source_slug == "broken":
            raise SourceNotQueryableError("no index")
        return [_make_result(chunk_id=f"{source_slug}-hit", source_slug=source_slug)]

    with patch("retrieval_hub.retrieval.api.query", side_effect=mock_query):
        results = multi_query(
            ["good", "broken"],
            "test query",
            session=session,
            top_k=5,
        )

    assert set(results.keys()) == {"good"}
    assert len(results["good"]) == 1


# ---------------------------------------------------------------------------
# doc_section pass-through tests
# ---------------------------------------------------------------------------


def test_multi_query_passes_doc_section(session):
    """multi_query forwards doc_section to each query() call."""
    from unittest.mock import patch

    captured_doc_sections: list = []

    def mock_query(
        source_slug, query_text, *, session, top_k, vectors_db_url=None, request_id=None,
        doc_section=None, scope_entity_id=None,
    ):
        captured_doc_sections.append(doc_section)
        return [_make_result(chunk_id=f"{source_slug}-hit", source_slug=source_slug)]

    with patch("retrieval_hub.retrieval.api.query", side_effect=mock_query):
        multi_query(
            ["src-a", "src-b"],
            "test query",
            session=session,
            top_k=5,
            doc_section=["Patient", "Condition"],
        )

    assert len(captured_doc_sections) == 2
    assert all(ds == ["Patient", "Condition"] for ds in captured_doc_sections)


def test_multi_query_passes_none_doc_section_by_default(session):
    """multi_query passes doc_section=None when not specified."""
    from unittest.mock import patch

    captured_doc_sections: list = []

    def mock_query(
        source_slug, query_text, *, session, top_k, vectors_db_url=None, request_id=None,
        doc_section=None, scope_entity_id=None,
    ):
        captured_doc_sections.append(doc_section)
        return [_make_result(chunk_id=f"{source_slug}-hit", source_slug=source_slug)]

    with patch("retrieval_hub.retrieval.api.query", side_effect=mock_query):
        multi_query(
            ["src-a"],
            "test query",
            session=session,
            top_k=5,
        )

    assert captured_doc_sections == [None]


def test_multi_query_passes_scope_entity_id(session):
    """multi_query forwards scope_entity_id to each query() call."""
    from unittest.mock import patch

    captured_scope_ids: list = []

    def mock_query(
        source_slug, query_text, *, session, top_k, vectors_db_url=None, request_id=None,
        doc_section=None, scope_entity_id=None,
    ):
        captured_scope_ids.append(scope_entity_id)
        return [_make_result(chunk_id=f"{source_slug}-hit", source_slug=source_slug)]

    with patch("retrieval_hub.retrieval.api.query", side_effect=mock_query):
        multi_query(
            ["src-a", "src-b"],
            "test query",
            session=session,
            top_k=5,
            scope_entity_id="patient-uuid-123",
        )

    assert len(captured_scope_ids) == 2
    assert all(sid == "patient-uuid-123" for sid in captured_scope_ids)
