"""Tests for the RetrievalHub MCP server tools.

Each test constructs mock dependencies (database session, retrieval function)
and calls the tool functions directly, bypassing FastMCP's dependency injection
layer. This validates the business logic without requiring a running database
or MCP transport.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastmcp.exceptions import ToolError
from retrieval_hub_mcp.schemas import (
    RefineHit,
    RefineResponse,
    RetrievalHit,
    RetrievalResponse,
    SourceDetail,
    SourceRetrievalMetadata,
    SourceSummary,
)
from retrieval_hub_mcp.server import (
    _parse_source_slugs,
    _resolve_embedding_model,
    _resolve_refine_strategy,
    describe_source,
    list_sources,
    refine,
    retrieve,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_source(
    slug="test-source",
    name="Test Source",
    family="document",
    status="published",
    description_short="A test source",
    description_long="A longer description of the test source",
    owner_team="platform",
    active_physical_index_id="pi-001",
    recipe_version_id="rv-001",
    id="src-001",
    usage_rules=None,
    rewriter_metadata=None,
    semantic_context=None,
):
    """Build a mock Source object with the fields the tools read."""
    return SimpleNamespace(
        id=id,
        slug=slug,
        name=name,
        family=family,
        status=status,
        description_short=description_short,
        description_long=description_long,
        owner_team=owner_team,
        active_physical_index_id=active_physical_index_id,
        recipe_version_id=recipe_version_id,
        usage_rules=usage_rules,
        rewriter_metadata=rewriter_metadata,
        semantic_context=semantic_context,
    )


def _make_physical_index(
    id="pi-001",
    document_count=42,
    build_metadata=None,
    recipe_version_id="rv-001",
):
    return SimpleNamespace(
        id=id,
        document_count=document_count,
        build_metadata=build_metadata,
        recipe_version_id=recipe_version_id,
    )


def _make_recipe_version(id="rv-001", content=None, version_number=1):
    return SimpleNamespace(
        id=id,
        content=content or {"parser": "docling", "chunker": "recursive"},
        version_number=version_number,
    )


def _make_sample_prompt(
    applies_to_llm_family="general",
    role="user",
    text="What documents cover topic X?",
):
    return SimpleNamespace(
        applies_to_llm_family=applies_to_llm_family,
        role=role,
        text=text,
    )


def _make_retrieval_result(
    chunk_id="chunk-uuid-000",
    text="Relevant passage text",
    score=0.92,
    doc_title="Manual v3",
    doc_url="https://example.com/manual-v3",
    doc_section="Chapter 2",
    chunk_index=0,
    physical_index_id="pi-001",
    recipe_version=1,
    request_id="req-abc",
):
    return SimpleNamespace(
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
    )


class _MockQuery:
    """Chainable mock that mimics SQLAlchemy's Query interface."""

    def __init__(self, results):
        self._results = results

    def filter(self, *args, **kwargs):
        return self

    def one_or_none(self):
        if isinstance(self._results, list):
            return self._results[0] if self._results else None
        return self._results

    def all(self):
        if isinstance(self._results, list):
            return self._results
        return [self._results] if self._results else []


# ---------------------------------------------------------------------------
# list_sources
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_sources_returns_summaries():
    """list_sources returns SourceSummary objects for active sources."""
    source = _make_source()
    pi = _make_physical_index()

    session = MagicMock()

    # First query() call returns sources, second returns physical index
    call_count = 0

    def mock_query(model):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return _MockQuery([source])
        return _MockQuery(pi)

    session.query.side_effect = mock_query

    results = await list_sources(session=session)

    assert len(results) == 1
    assert isinstance(results[0], SourceSummary)
    assert results[0].slug == "test-source"
    assert results[0].name == "Test Source"
    assert results[0].family == "document"
    assert results[0].status == "published"
    assert results[0].description_short == "A test source"
    assert results[0].document_count == 42


@pytest.mark.asyncio
async def test_list_sources_no_active_index():
    """Sources without an active physical index get document_count=None."""
    source = _make_source(active_physical_index_id=None)

    session = MagicMock()
    session.query.return_value = _MockQuery([source])

    results = await list_sources(session=session)

    assert len(results) == 1
    assert results[0].document_count is None


@pytest.mark.asyncio
async def test_list_sources_empty_catalog():
    """An empty catalog returns an empty list, not an error."""
    session = MagicMock()
    session.query.return_value = _MockQuery([])

    results = await list_sources(session=session)

    assert results == []


# ---------------------------------------------------------------------------
# describe_source
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_describe_source_found():
    """describe_source returns full detail for an existing source."""
    source = _make_source()
    pi = _make_physical_index(build_metadata={"chunk_count": 500})
    prompt = _make_sample_prompt()

    session = MagicMock()

    call_count = 0

    def mock_query(model):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            # Source lookup
            return _MockQuery(source)
        elif call_count == 2:
            # PhysicalIndex lookup
            return _MockQuery(pi)
        elif call_count == 3:
            # SamplePrompt lookup
            return _MockQuery([prompt])
        return _MockQuery(None)

    session.query.side_effect = mock_query

    result = await describe_source(slug="test-source", session=session)

    assert isinstance(result, SourceDetail)
    assert result.slug == "test-source"
    assert result.name == "Test Source"
    assert result.description_long == "A longer description of the test source"
    assert result.owner_team == "platform"
    assert result.document_count == 42
    assert result.chunk_count == 500
    assert result.sample_prompts is not None
    assert len(result.sample_prompts) == 1
    assert result.sample_prompts[0]["role"] == "user"
    assert result.sample_prompts[0]["text"] == "What documents cover topic X?"


@pytest.mark.asyncio
async def test_describe_source_not_found():
    """describe_source raises ToolError for a missing slug."""
    from fastmcp.exceptions import ToolError

    session = MagicMock()
    session.query.return_value = _MockQuery(None)

    with pytest.raises(ToolError, match="No source with slug"):
        await describe_source(slug="nonexistent", session=session)


@pytest.mark.asyncio
async def test_describe_source_no_index_or_prompts():
    """describe_source handles sources with no active index or sample prompts."""
    source = _make_source(recipe_version_id=None, active_physical_index_id=None)

    session = MagicMock()

    call_count = 0

    def mock_query(model):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            # Source lookup
            return _MockQuery(source)
        elif call_count == 2:
            # SamplePrompt lookup (no recipe/index queries since IDs are None)
            return _MockQuery([])
        return _MockQuery(None)

    session.query.side_effect = mock_query

    result = await describe_source(slug="test-source", session=session)

    assert result.sample_prompts is None
    assert result.document_count is None
    assert result.chunk_count is None


# ---------------------------------------------------------------------------
# Retrieve session helpers
# ---------------------------------------------------------------------------


def _make_retrieve_session(source=None, embedding_model="test-embed-model"):
    """Build a mock session for retrieve/refine tests.

    Dispatches by model class so Source, PhysicalIndex, and RecipeVersion
    queries each return the correct mock object.
    """
    from retrieval_hub.models import PhysicalIndex as PIModel
    from retrieval_hub.models import RecipeVersion as RVModel
    from retrieval_hub.models import Source as SModel

    pi = _make_physical_index()
    rv = _make_recipe_version(
        content={"embedding": {"model": embedding_model}},
    )

    session = MagicMock()

    def mock_query(model):
        if model is SModel:
            return _MockQuery(source)
        if model is PIModel:
            return _MockQuery(pi)
        if model is RVModel:
            return _MockQuery(rv)
        return _MockQuery(None)

    session.query.side_effect = mock_query
    return session


# ---------------------------------------------------------------------------
# retrieve — vector search path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_retrieve_delegates_to_query():
    """retrieve delegates to retrieval_hub.retrieval.api.query and maps results."""
    mock_results = [
        _make_retrieval_result(),
        _make_retrieval_result(
            text="Second passage",
            score=0.85,
            doc_section=None,
        ),
    ]

    source = _make_source()
    session = _make_retrieve_session(source)

    with patch("retrieval_hub_mcp.server.retrieval_query", return_value=mock_results):
        resp = await retrieve(
            query="test query",
            source="test-source",
            top_k=5,
            session=session,
        )

    assert isinstance(resp, RetrievalResponse)
    assert len(resp.hits) == 2
    assert isinstance(resp.hits[0], RetrievalHit)
    assert resp.hits[0].chunk_id == "chunk-uuid-000"
    assert resp.hits[0].text == "Relevant passage text"
    assert resp.hits[0].score == 0.92
    assert resp.hits[0].doc_title == "Manual v3"
    assert resp.hits[0].doc_url == "https://example.com/manual-v3"
    assert resp.hits[0].doc_section == "Chapter 2"
    assert resp.hits[0].chunk_index == 0
    assert resp.request_id == "req-abc"
    assert resp.embedding_model == "test-embed-model"

    assert resp.hits[1].doc_section is None


@pytest.mark.asyncio
async def test_retrieve_source_not_found():
    """retrieve raises ToolError when the source slug doesn't exist."""
    from fastmcp.exceptions import ToolError

    from retrieval_hub.retrieval.api import SourceNotFoundError

    session = _make_retrieve_session(None)

    with patch(
        "retrieval_hub_mcp.server.retrieval_query",
        side_effect=SourceNotFoundError("No source with slug 'missing'"),
    ):
        with pytest.raises(ToolError, match="not found"):
            await retrieve(
                query="test",
                source="missing",
                session=session,
            )


@pytest.mark.asyncio
async def test_retrieve_source_not_queryable():
    """retrieve raises ToolError when the source has no active index."""
    from fastmcp.exceptions import ToolError

    from retrieval_hub.retrieval.api import SourceNotQueryableError

    session = _make_retrieve_session(None)

    with patch(
        "retrieval_hub_mcp.server.retrieval_query",
        side_effect=SourceNotQueryableError("No active index"),
    ):
        with pytest.raises(ToolError, match="no active index"):
            await retrieve(
                query="test",
                source="wip-source",
                session=session,
            )


@pytest.mark.asyncio
async def test_retrieve_unsupported_family():
    """retrieve raises ToolError for sources with unsupported families."""
    from fastmcp.exceptions import ToolError

    from retrieval_hub.retrieval.api import UnsupportedFamilyError

    session = _make_retrieve_session(None)

    with patch(
        "retrieval_hub_mcp.server.retrieval_query",
        side_effect=UnsupportedFamilyError("No adapter for 'graph'"),
    ):
        with pytest.raises(ToolError, match="not yet supported"):
            await retrieve(
                query="test",
                source="graph-source",
                session=session,
            )


@pytest.mark.asyncio
async def test_retrieve_passes_top_k():
    """retrieve forwards the top_k parameter to the retrieval function."""
    source = _make_source()
    session = _make_retrieve_session(source)

    with patch("retrieval_hub_mcp.server.retrieval_query", return_value=[]) as mock_q:
        await retrieve(
            query="test query",
            source="test-source",
            top_k=3,
            session=session,
        )

    mock_q.assert_called_once_with(
        source_slug="test-source",
        query_text="test query",
        session=session,
        top_k=3,
    )


# ---------------------------------------------------------------------------
# retrieve — file_path (GitHub file fetch) path
# ---------------------------------------------------------------------------


def _make_file_fetch_session(source, pi, rv):
    """Build a mock session for file_path tests.

    The resolve chain is: Source -> PhysicalIndex -> RecipeVersion.
    """
    call_count = 0

    def mock_query(model):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return _MockQuery(source)
        if call_count == 2:
            return _MockQuery(pi)
        return _MockQuery(rv)

    session = MagicMock()
    session.query.side_effect = mock_query
    return session


@pytest.mark.asyncio
async def test_retrieve_file_path_fetches_from_github():
    """When file_path is provided, retrieve fetches from GitHub instead of vector search."""
    source = _make_source(active_physical_index_id="pi-001")
    pi = _make_physical_index(id="pi-001")
    pi.recipe_version_id = "rv-001"
    rv = _make_recipe_version(content={"github_repo": "rdwj/retrieval-hub"})

    session = _make_file_fetch_session(source, pi, rv)

    with patch(
        "retrieval_hub_mcp.server._fetch_github_file",
        new_callable=AsyncMock,
        return_value=("print('hello')\n", "https://github.com/rdwj/retrieval-hub/blob/main/hello.py"),
    ) as mock_fetch:
        resp = await retrieve(
            query="unused",
            source="test-source",
            file_path="hello.py",
            session=session,
        )

    mock_fetch.assert_awaited_once_with("rdwj/retrieval-hub", "hello.py", None)
    assert isinstance(resp, RetrievalResponse)
    assert len(resp.hits) == 1
    assert resp.hits[0].score == 1.0
    assert resp.hits[0].text == "print('hello')\n"
    assert resp.hits[0].doc_title == "hello.py"
    assert resp.embedding_model is None


@pytest.mark.asyncio
async def test_retrieve_file_path_with_ref():
    """file_path + ref are forwarded to the GitHub fetch."""
    source = _make_source(active_physical_index_id="pi-001")
    pi = _make_physical_index(id="pi-001")
    pi.recipe_version_id = "rv-001"
    rv = _make_recipe_version(content={"github_repo": "rdwj/retrieval-hub"})

    session = _make_file_fetch_session(source, pi, rv)

    with patch(
        "retrieval_hub_mcp.server._fetch_github_file",
        new_callable=AsyncMock,
        return_value=("old code\n", "https://github.com/rdwj/retrieval-hub/blob/abc123/hello.py"),
    ) as mock_fetch:
        resp = await retrieve(
            query="unused",
            source="test-source",
            file_path="hello.py",
            ref="abc123",
            session=session,
        )

    mock_fetch.assert_awaited_once_with("rdwj/retrieval-hub", "hello.py", "abc123")
    assert len(resp.hits) == 1
    assert resp.request_id  # generated UUID


@pytest.mark.asyncio
async def test_retrieve_file_path_no_github_repo():
    """file_path raises ToolError when the recipe has no github_repo."""
    from fastmcp.exceptions import ToolError

    source = _make_source(active_physical_index_id="pi-001")
    pi = _make_physical_index(id="pi-001")
    pi.recipe_version_id = "rv-001"
    rv = _make_recipe_version(content={"parser": "docling"})

    session = _make_file_fetch_session(source, pi, rv)

    with pytest.raises(ToolError, match="github_repo"):
        await retrieve(
            query="unused",
            source="test-source",
            file_path="some/file.py",
            session=session,
        )


@pytest.mark.asyncio
async def test_retrieve_file_path_source_not_found():
    """file_path raises ToolError when the source doesn't exist."""
    from fastmcp.exceptions import ToolError

    session = _make_retrieve_session(None)

    with pytest.raises(ToolError, match="not found"):
        await retrieve(
            query="unused",
            source="nonexistent",
            file_path="some/file.py",
            session=session,
        )


# ---------------------------------------------------------------------------
# retrieve --- rewriter integration
# ---------------------------------------------------------------------------

_REWRITER_META = {
    "enabled": True,
    "vocabulary_mappings": [],
    "sample_queries": [],
    "max_rewrites": 3,
}


@pytest.mark.asyncio
async def test_retrieve_with_rewrite_enabled():
    """When rewriter_metadata is enabled, retrieve fans out queries and merges hits."""
    source = _make_source(rewriter_metadata=_REWRITER_META)
    session = _make_retrieve_session(source)

    rewrite_result = SimpleNamespace(
        queries=[
            SimpleNamespace(
                text="rewritten query 1",
                intent="intent1",
                confidence=0.95,
                rationale="r1",
            ),
            SimpleNamespace(
                text="rewritten query 2",
                intent="intent2",
                confidence=0.85,
                rationale="r2",
            ),
        ],
    )

    def _retrieval_side_effect(**kwargs):
        qt = kwargs["query_text"]
        if qt == "original query":
            return [_make_retrieval_result(text="original hit", score=0.8)]
        if qt == "rewritten query 1":
            return [_make_retrieval_result(text="rewrite hit 1", score=0.9)]
        if qt == "rewritten query 2":
            return [_make_retrieval_result(text="rewrite hit 2", score=0.7)]
        return []

    with (
        patch(
            "retrieval_hub_mcp.server._rewrite_query",
            new_callable=AsyncMock,
            return_value=rewrite_result,
        ),
        patch(
            "retrieval_hub_mcp.server.retrieval_query",
            side_effect=_retrieval_side_effect,
        ) as mock_rq,
    ):
        resp = await retrieve(
            query="original query",
            source="test-source",
            top_k=5,
            session=session,
        )

    assert resp.rewritten_queries is not None
    assert len(resp.rewritten_queries) == 2
    assert resp.rewritten_queries[0].text == "rewritten query 1"
    assert resp.rewritten_queries[1].text == "rewritten query 2"

    hit_texts = {h.text for h in resp.hits}
    assert "original hit" in hit_texts
    assert "rewrite hit 1" in hit_texts
    assert "rewrite hit 2" in hit_texts

    assert mock_rq.call_count == 3


@pytest.mark.asyncio
async def test_retrieve_with_no_rewrite_flag():
    """no_rewrite=True skips the rewriter even when metadata is enabled."""
    source = _make_source(rewriter_metadata=_REWRITER_META)
    session = _make_retrieve_session(source)

    with (
        patch(
            "retrieval_hub_mcp.server._rewrite_query",
            new_callable=AsyncMock,
        ) as mock_rewrite,
        patch(
            "retrieval_hub_mcp.server.retrieval_query",
            return_value=[_make_retrieval_result()],
        ) as mock_rq,
    ):
        resp = await retrieve(
            query="test query",
            source="test-source",
            top_k=5,
            no_rewrite=True,
            session=session,
        )

    assert resp.rewritten_queries is None
    mock_rewrite.assert_not_awaited()
    mock_rq.assert_called_once()


@pytest.mark.asyncio
async def test_retrieve_without_rewriter_metadata():
    """Sources without rewriter_metadata behave as before (no rewriting)."""
    source = _make_source(rewriter_metadata=None)
    session = _make_retrieve_session(source)

    with patch(
        "retrieval_hub_mcp.server.retrieval_query",
        return_value=[_make_retrieval_result()],
    ) as mock_rq:
        resp = await retrieve(
            query="test query",
            source="test-source",
            top_k=5,
            session=session,
        )

    assert resp.rewritten_queries is None
    assert len(resp.hits) == 1
    mock_rq.assert_called_once()


@pytest.mark.asyncio
async def test_retrieve_rewriter_fallback_on_error():
    """When the rewriter raises, retrieve falls back to the raw query."""
    source = _make_source(rewriter_metadata=_REWRITER_META)
    session = _make_retrieve_session(source)

    with (
        patch(
            "retrieval_hub_mcp.server._rewrite_query",
            new_callable=AsyncMock,
            side_effect=Exception("LLM unreachable"),
        ),
        patch(
            "retrieval_hub_mcp.server.retrieval_query",
            return_value=[_make_retrieval_result(text="fallback hit")],
        ) as mock_rq,
    ):
        resp = await retrieve(
            query="test query",
            source="test-source",
            top_k=5,
            session=session,
        )

    assert resp.rewritten_queries is None
    assert len(resp.hits) == 1
    assert resp.hits[0].text == "fallback hit"
    mock_rq.assert_called_once()


@pytest.mark.asyncio
async def test_retrieve_deduplicates_hits():
    """Duplicate hits from original and rewritten queries are deduplicated by text."""
    source = _make_source(rewriter_metadata=_REWRITER_META)
    session = _make_retrieve_session(source)

    rewrite_result = SimpleNamespace(
        queries=[
            SimpleNamespace(
                text="rewritten query",
                intent="synonym",
                confidence=0.90,
                rationale="r",
            ),
        ],
    )

    def _retrieval_side_effect(**kwargs):
        qt = kwargs["query_text"]
        if qt == "test query":
            return [_make_retrieval_result(text="shared passage", score=0.7)]
        if qt == "rewritten query":
            return [_make_retrieval_result(text="shared passage", score=0.9)]
        return []

    with (
        patch(
            "retrieval_hub_mcp.server._rewrite_query",
            new_callable=AsyncMock,
            return_value=rewrite_result,
        ),
        patch(
            "retrieval_hub_mcp.server.retrieval_query",
            side_effect=_retrieval_side_effect,
        ),
    ):
        resp = await retrieve(
            query="test query",
            source="test-source",
            top_k=5,
            session=session,
        )

    assert len(resp.hits) == 1
    assert resp.hits[0].text == "shared passage"
    assert resp.hits[0].score == 0.9


# ---------------------------------------------------------------------------
# refine
# ---------------------------------------------------------------------------


def _make_refine_result(
    chunk_id="refine-uuid-000",
    text="Adjacent chunk text",
    score=1.0,
    doc_title="Manual v3",
    doc_url="https://example.com/manual-v3",
    doc_section="Chapter 2",
    chunk_index=0,
    physical_index_id="pi-001",
    recipe_version=1,
    request_id="req-refine",
):
    return SimpleNamespace(
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
    )


def _make_refine_output(results, *, truncated=False, total_chunks=None):
    """Wrap refine results in a RefineOutput-like namespace."""
    return SimpleNamespace(
        results=results,
        truncated=truncated,
        total_chunks=total_chunks,
    )


@pytest.mark.asyncio
async def test_refine_returns_section_chunks():
    """refine delegates to retrieval_refine and maps results to RefineResponse.

    A ``document`` family source defaults to the ``section`` strategy.
    """
    mock_results = [
        _make_refine_result(text="before", chunk_index=4),
        _make_refine_result(text="target", chunk_index=5),
        _make_refine_result(text="after", chunk_index=6),
    ]

    source = _make_source()
    session = _make_retrieve_session(source)

    with patch(
        "retrieval_hub_mcp.server.retrieval_refine",
        return_value=_make_refine_output(mock_results),
    ):
        resp = await refine(
            source="test-source",
            doc_title="Manual v3",
            chunk_index=5,
            query="tell me more",
            window=1,
            session=session,
        )

    assert isinstance(resp, RefineResponse)
    assert resp.source == "test-source"
    assert resp.doc_title == "Manual v3"
    assert resp.doc_url == "https://example.com/manual-v3"
    assert resp.origin_chunk_index == 5
    assert resp.strategy == "section"
    assert not resp.truncated
    assert resp.embedding_model == "test-embed-model"
    assert len(resp.chunks) == 3
    assert isinstance(resp.chunks[0], RefineHit)
    assert resp.chunks[0].chunk_id == "refine-uuid-000"
    assert resp.chunks[0].text == "before"
    assert resp.chunks[0].is_origin is False
    assert resp.chunks[0].doc_title is None
    assert resp.chunks[0].doc_url is None
    assert resp.chunks[1].is_origin is True
    assert resp.chunks[2].is_origin is False


@pytest.mark.asyncio
async def test_refine_source_not_found():
    """refine raises ToolError for a missing source slug."""
    from fastmcp.exceptions import ToolError

    from retrieval_hub.retrieval.api import SourceNotFoundError

    session = _make_retrieve_session(None)

    with patch(
        "retrieval_hub_mcp.server.retrieval_refine",
        side_effect=SourceNotFoundError("No source"),
    ):
        with pytest.raises(ToolError, match="not found"):
            await refine(
                source="missing",
                doc_title="Doc",
                chunk_index=0,
                query="more",
                session=session,
            )


@pytest.mark.asyncio
async def test_refine_passes_window_and_strategy():
    """refine forwards window, strategy, and max_context_tokens to retrieval_refine."""
    source = _make_source()
    session = _make_retrieve_session(source)
    mock_results = [_make_refine_result(chunk_index=3)]

    with patch(
        "retrieval_hub_mcp.server.retrieval_refine",
        return_value=_make_refine_output(mock_results),
    ) as mock_ref:
        await refine(
            source="test-source",
            doc_title="Manual v3",
            chunk_index=3,
            query="details",
            window=5,
            session=session,
        )

    mock_ref.assert_called_once_with(
        source_slug="test-source",
        doc_title="Manual v3",
        chunk_index=3,
        query_text="details",
        window=5,
        session=session,
        strategy="section",
        max_context_tokens=None,
    )


@pytest.mark.asyncio
async def test_refine_empty_result_raises_tool_error():
    """refine raises ToolError with actionable guidance when no chunks are found."""
    from fastmcp.exceptions import ToolError

    source = _make_source()
    session = _make_retrieve_session(source)

    with patch(
        "retrieval_hub_mcp.server.retrieval_refine",
        return_value=_make_refine_output([]),
    ):
        with pytest.raises(ToolError, match="No chunks found"):
            await refine(
                source="test-source",
                doc_title="Wrong Title",
                chunk_index=999,
                query="more",
                session=session,
            )


@pytest.mark.asyncio
async def test_refine_includes_usage_rules():
    """refine passes usage_rules and data_freshness through from the source."""
    source = _make_source(
        usage_rules={
            "citation": "Cite as VA CPG",
            "data_freshness": {
                "source_name": "VA CPG",
                "last_refreshed": "2026-01-15",
            },
        }
    )
    session = _make_retrieve_session(source)
    mock_results = [_make_refine_result(chunk_index=0)]

    with patch(
        "retrieval_hub_mcp.server.retrieval_refine",
        return_value=_make_refine_output(mock_results),
    ):
        resp = await refine(
            source="test-source",
            doc_title="Manual v3",
            chunk_index=0,
            query="more",
            session=session,
        )

    assert resp.usage_rules is not None
    assert resp.usage_rules.citation == "Cite as VA CPG"
    assert resp.data_freshness is not None
    assert resp.data_freshness.last_refreshed == "2026-01-15"


@pytest.mark.asyncio
async def test_refine_strategy_from_source_semantic_context():
    """semantic_context.refinement_strategies overrides the family default strategy."""
    source = _make_source(
        semantic_context={
            "refinement_strategies": [
                {"kind": "adjacent", "window": 3, "enabled": True},
            ],
        },
    )
    session = _make_retrieve_session(source)
    mock_results = [_make_refine_result(chunk_index=0)]

    with patch(
        "retrieval_hub_mcp.server.retrieval_refine",
        return_value=_make_refine_output(mock_results),
    ) as mock_ref:
        await refine(
            source="test-source",
            doc_title="Manual v3",
            chunk_index=0,
            query="more",
            session=session,
        )

    # The source is family="document" which defaults to "section",
    # but semantic_context overrides it to "adjacent".
    mock_ref.assert_called_once()
    call_kwargs = mock_ref.call_args[1]
    assert call_kwargs["strategy"] == "adjacent"


@pytest.mark.asyncio
async def test_refine_truncated_response():
    """When truncated=True, response carries truncation metadata."""
    source = _make_source()
    session = _make_retrieve_session(source)
    mock_results = [
        _make_refine_result(text="chunk A", chunk_index=4),
        _make_refine_result(text="chunk B", chunk_index=5),
    ]

    with patch(
        "retrieval_hub_mcp.server.retrieval_refine",
        return_value=_make_refine_output(mock_results, truncated=True, total_chunks=15),
    ):
        resp = await refine(
            source="test-source",
            doc_title="Manual v3",
            chunk_index=5,
            query="more",
            session=session,
        )

    assert resp.truncated is True
    assert resp.total_section_chunks == 15


@pytest.mark.asyncio
async def test_refine_max_context_tokens_passed_through():
    """max_context_tokens is forwarded to retrieval_refine."""
    source = _make_source()
    session = _make_retrieve_session(source)
    mock_results = [_make_refine_result(chunk_index=3)]

    with patch(
        "retrieval_hub_mcp.server.retrieval_refine",
        return_value=_make_refine_output(mock_results),
    ) as mock_ref:
        await refine(
            source="test-source",
            doc_title="Manual v3",
            chunk_index=3,
            query="details",
            max_context_tokens=4000,
            session=session,
        )

    mock_ref.assert_called_once()
    call_kwargs = mock_ref.call_args[1]
    assert call_kwargs["max_context_tokens"] == 4000


@pytest.mark.asyncio
async def test_refine_code_source_defaults_to_adjacent():
    """A code-family source with no semantic_context defaults to 'adjacent' strategy."""
    source = _make_source(family="code")
    session = _make_retrieve_session(source)
    mock_results = [_make_refine_result(chunk_index=0)]

    with patch(
        "retrieval_hub_mcp.server.retrieval_refine",
        return_value=_make_refine_output(mock_results),
    ) as mock_ref:
        await refine(
            source="test-source",
            doc_title="main.py",
            chunk_index=0,
            query="context",
            session=session,
        )

    mock_ref.assert_called_once()
    call_kwargs = mock_ref.call_args[1]
    assert call_kwargs["strategy"] == "adjacent"


# ---------------------------------------------------------------------------
# refine — cross-reference strategy
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_refine_cross_reference_strategy():
    """cross_reference strategy returns multi-doc results with per-hit doc fields."""
    source = _make_source(
        semantic_context={
            "refinement_strategies": [
                {"kind": "section", "window": 2, "enabled": True, "max_context_tokens": 4000},
                {"kind": "cross_reference", "window": 5, "enabled": True, "max_context_tokens": 4000},
            ],
        },
    )
    session = _make_retrieve_session(source)

    mock_results = [
        _make_refine_result(
            text="PTSD origin chunk",
            doc_title="PTSD Doc",
            doc_url="https://example.com/ptsd",
            chunk_index=10,
        ),
        _make_refine_result(
            text="SUD cross-ref hit 1",
            doc_title="SUD Doc",
            doc_url="https://example.com/sud",
            chunk_index=15,
        ),
        _make_refine_result(
            text="SUD cross-ref hit 2",
            doc_title="SUD Doc",
            doc_url="https://example.com/sud",
            chunk_index=22,
        ),
    ]

    with patch(
        "retrieval_hub_mcp.server.retrieval_refine",
        return_value=_make_refine_output(mock_results),
    ) as mock_ref:
        resp = await refine(
            source="test-source",
            doc_title="PTSD Doc",
            chunk_index=10,
            query="substance use",
            strategy="cross_reference",
            session=session,
        )

    assert resp.strategy == "cross_reference"
    assert len(resp.chunks) == 3

    # Origin chunk
    assert resp.chunks[0].is_origin is True
    assert resp.chunks[0].doc_title == "PTSD Doc"
    assert resp.chunks[0].doc_url == "https://example.com/ptsd"

    # Cross-reference chunks
    assert resp.chunks[1].doc_title == "SUD Doc"
    assert resp.chunks[1].is_origin is False
    assert resp.chunks[2].doc_title == "SUD Doc"
    assert resp.chunks[2].is_origin is False

    # All chunks have non-None doc fields for cross_reference strategy
    for chunk in resp.chunks:
        assert chunk.doc_title is not None
        assert chunk.doc_url is not None

    # Verify retrieval_refine was called with the right strategy
    mock_ref.assert_called_once()
    assert mock_ref.call_args[1]["strategy"] == "cross_reference"


@pytest.mark.asyncio
async def test_refine_explicit_strategy_overrides_default():
    """An explicit strategy parameter overrides the source's default (first enabled entry)."""
    source = _make_source(
        semantic_context={
            "refinement_strategies": [
                {"kind": "section", "window": 2, "enabled": True, "max_context_tokens": 4000},
                {"kind": "cross_reference", "window": 5, "enabled": True, "max_context_tokens": 4000},
            ],
        },
    )
    session = _make_retrieve_session(source)
    mock_results = [_make_refine_result(chunk_index=0)]

    with patch(
        "retrieval_hub_mcp.server.retrieval_refine",
        return_value=_make_refine_output(mock_results),
    ) as mock_ref:
        resp = await refine(
            source="test-source",
            doc_title="Manual v3",
            chunk_index=0,
            query="more context",
            strategy="cross_reference",
            session=session,
        )

    # The source's first enabled strategy is "section", but the explicit
    # parameter should override it.
    mock_ref.assert_called_once()
    assert mock_ref.call_args[1]["strategy"] == "cross_reference"
    assert resp.strategy == "cross_reference"


@pytest.mark.asyncio
async def test_refine_cross_reference_per_hit_doc_fields():
    """cross_reference populates per-hit doc fields; section leaves them None."""
    source = _make_source(
        semantic_context={
            "refinement_strategies": [
                {"kind": "section", "window": 2, "enabled": True},
                {"kind": "cross_reference", "window": 5, "enabled": True},
            ],
        },
    )
    mock_results = [
        _make_refine_result(
            doc_title="Doc A",
            doc_url="https://example.com/a",
            chunk_index=3,
        ),
    ]

    # Call 1: cross_reference — per-hit doc fields populated
    session_xref = _make_retrieve_session(source)
    with patch(
        "retrieval_hub_mcp.server.retrieval_refine",
        return_value=_make_refine_output(mock_results),
    ):
        resp_xref = await refine(
            source="test-source",
            doc_title="Doc A",
            chunk_index=3,
            query="related content",
            strategy="cross_reference",
            session=session_xref,
        )

    for chunk in resp_xref.chunks:
        assert chunk.doc_title is not None, "cross_reference should populate doc_title"
        assert chunk.doc_url is not None, "cross_reference should populate doc_url"

    # Call 2: section (default, no explicit strategy) — per-hit doc fields None
    session_section = _make_retrieve_session(source)
    with patch(
        "retrieval_hub_mcp.server.retrieval_refine",
        return_value=_make_refine_output(mock_results),
    ):
        resp_section = await refine(
            source="test-source",
            doc_title="Doc A",
            chunk_index=3,
            query="related content",
            session=session_section,
        )

    for chunk in resp_section.chunks:
        assert chunk.doc_title is None, "section strategy should leave doc_title None"
        assert chunk.doc_url is None, "section strategy should leave doc_url None"


@pytest.mark.asyncio
async def test_refine_cross_reference_is_origin_correct():
    """is_origin matches on both chunk_index AND doc_title, not chunk_index alone."""
    source = _make_source(
        semantic_context={
            "refinement_strategies": [
                {"kind": "cross_reference", "window": 5, "enabled": True},
            ],
        },
    )
    session = _make_retrieve_session(source)

    # Result 2 has the same chunk_index as the origin but a different doc_title.
    mock_results = [
        _make_refine_result(
            text="PTSD chunk 10 — the actual origin",
            doc_title="PTSD Doc",
            doc_url="https://example.com/ptsd",
            chunk_index=10,
        ),
        _make_refine_result(
            text="SUD chunk 10 — same index, different doc",
            doc_title="SUD Doc",
            doc_url="https://example.com/sud",
            chunk_index=10,
        ),
        _make_refine_result(
            text="SUD chunk 20",
            doc_title="SUD Doc",
            doc_url="https://example.com/sud",
            chunk_index=20,
        ),
    ]

    with patch(
        "retrieval_hub_mcp.server.retrieval_refine",
        return_value=_make_refine_output(mock_results),
    ):
        resp = await refine(
            source="test-source",
            doc_title="PTSD Doc",
            chunk_index=10,
            query="comorbidity",
            strategy="cross_reference",
            session=session,
        )

    assert resp.chunks[0].is_origin is True, (
        "PTSD Doc chunk 10 should be the origin"
    )
    assert resp.chunks[1].is_origin is False, (
        "SUD Doc chunk 10 shares the index but is a different document"
    )
    assert resp.chunks[2].is_origin is False


# ---------------------------------------------------------------------------
# _resolve_refine_strategy — entity_arc and min_score tests
# ---------------------------------------------------------------------------


def test_resolve_refine_strategy_entity_arc_from_source_config():
    """entity_arc strategy with min_score is resolved from source semantic_context."""
    source = _make_source(
        semantic_context={
            "refinement_strategies": [
                {"kind": "entity_arc", "window": 10, "enabled": True, "min_score": 0.35},
            ],
        },
    )

    strategy, max_tokens, window, min_score = _resolve_refine_strategy(
        source, None, None, None,
    )

    assert strategy == "entity_arc"
    assert window == 10
    assert min_score == pytest.approx(0.35)
    assert max_tokens is None


def test_resolve_refine_strategy_entity_arc_explicit_override():
    """Explicit strategy='entity_arc' picks up min_score from matching config entry."""
    source = _make_source(
        semantic_context={
            "refinement_strategies": [
                {"kind": "section", "window": 2, "enabled": True},
                {"kind": "entity_arc", "window": 8, "enabled": True, "min_score": 0.40, "max_context_tokens": 6000},
            ],
        },
    )

    strategy, max_tokens, window, min_score = _resolve_refine_strategy(
        source, "entity_arc", None, None,
    )

    assert strategy == "entity_arc"
    assert window == 8
    assert min_score == pytest.approx(0.40)
    assert max_tokens == 6000


def test_resolve_refine_strategy_tool_window_overrides_source():
    """Tool-level window overrides the source config's window."""
    source = _make_source(
        semantic_context={
            "refinement_strategies": [
                {"kind": "entity_arc", "window": 10, "enabled": True, "min_score": 0.35},
            ],
        },
    )

    strategy, max_tokens, window, min_score = _resolve_refine_strategy(
        source, "entity_arc", None, 20,
    )

    assert strategy == "entity_arc"
    assert window == 20  # tool override
    assert min_score == pytest.approx(0.35)  # from source, no tool override


def test_resolve_refine_strategy_min_score_defaults_none():
    """min_score defaults to None when not configured on the source."""
    source = _make_source(
        semantic_context={
            "refinement_strategies": [
                {"kind": "section", "window": 2, "enabled": True},
            ],
        },
    )

    _, _, _, min_score = _resolve_refine_strategy(source, None, None, None)
    assert min_score is None


@pytest.mark.asyncio
async def test_refine_entity_arc_strategy():
    """entity_arc strategy returns scored results with is_origin=False for all chunks."""
    source = _make_source(
        semantic_context={
            "refinement_strategies": [
                {"kind": "entity_arc", "window": 10, "enabled": True, "min_score": 0.30},
            ],
        },
    )
    session = _make_retrieve_session(source)

    mock_results = [
        _make_refine_result(
            text="SSRI mention 1",
            doc_title="PTSD Doc",
            doc_url="https://example.com/ptsd",
            chunk_index=17,
            score=0.55,
        ),
        _make_refine_result(
            text="SSRI mention 2",
            doc_title="PTSD Doc",
            doc_url="https://example.com/ptsd",
            chunk_index=33,
            score=0.48,
        ),
    ]

    with patch(
        "retrieval_hub_mcp.server.retrieval_refine",
        return_value=_make_refine_output(mock_results),
    ) as mock_ref:
        resp = await refine(
            source="test-source",
            doc_title="PTSD Doc",
            chunk_index=0,
            query="SSRIs",
            strategy="entity_arc",
            session=session,
        )

    assert resp.strategy == "entity_arc"
    assert resp.origin_chunk_index == -1
    assert len(resp.chunks) == 2
    # entity_arc sets is_origin=False for all chunks
    assert all(not c.is_origin for c in resp.chunks)
    # doc_title/doc_url are None (not cross_reference)
    assert all(c.doc_title is None for c in resp.chunks)

    mock_ref.assert_called_once()
    call_kwargs = mock_ref.call_args[1]
    assert call_kwargs["strategy"] == "entity_arc"
    assert call_kwargs["min_score"] == pytest.approx(0.30)


@pytest.mark.asyncio
async def test_refine_by_chunk_id():
    """When chunk_id is provided, refine resolves doc_title/chunk_index from it."""
    source = _make_source()
    session = _make_retrieve_session(source)

    mock_results = [
        _make_refine_result(chunk_id="target-uuid", text="target", chunk_index=7),
    ]

    with (
        patch(
            "retrieval_hub_mcp.server.resolve_chunk_id",
            return_value=("Manual v3", 7),
        ) as mock_resolve,
        patch(
            "retrieval_hub_mcp.server.retrieval_refine",
            return_value=_make_refine_output(mock_results),
        ) as mock_ref,
    ):
        resp = await refine(
            source="test-source",
            doc_title="",
            chunk_index=0,
            query="tell me more",
            chunk_id="target-uuid",
            session=session,
        )

    mock_resolve.assert_called_once_with(
        "test-source", "target-uuid", session=session,
    )
    call_kwargs = mock_ref.call_args[1]
    assert call_kwargs["doc_title"] == "Manual v3"
    assert call_kwargs["chunk_index"] == 7

    assert isinstance(resp, RefineResponse)
    assert resp.doc_title == "Manual v3"
    assert resp.origin_chunk_index == 7
    assert len(resp.chunks) == 1
    assert resp.chunks[0].chunk_id == "target-uuid"


@pytest.mark.asyncio
async def test_refine_by_chunk_id_not_found():
    """When chunk_id does not exist, refine raises ToolError."""
    source = _make_source()
    session = _make_retrieve_session(source)

    with (
        patch(
            "retrieval_hub_mcp.server.resolve_chunk_id",
            side_effect=LookupError("No chunk with id 'bad-uuid'"),
        ),
        pytest.raises(ToolError, match="chunk_id.*not found"),
    ):
        await refine(
            source="test-source",
            doc_title="",
            chunk_index=0,
            query="tell me more",
            chunk_id="bad-uuid",
            session=session,
        )


# ---------------------------------------------------------------------------
# _resolve_embedding_model
# ---------------------------------------------------------------------------


def test_resolve_embedding_model_from_recipe():
    """_resolve_embedding_model returns the model name from the recipe content."""
    from retrieval_hub.models import PhysicalIndex as PIModel
    from retrieval_hub.models import RecipeVersion as RVModel

    source = _make_source()
    pi = _make_physical_index()
    rv = _make_recipe_version(
        content={"embedding": {"model": "NeuML/pubmedbert-base-embeddings"}},
    )

    session = MagicMock()

    def mock_query(model):
        if model is PIModel:
            return _MockQuery(pi)
        if model is RVModel:
            return _MockQuery(rv)
        return _MockQuery(None)

    session.query.side_effect = mock_query

    assert _resolve_embedding_model(source, session) == "NeuML/pubmedbert-base-embeddings"


def test_resolve_embedding_model_no_active_index():
    """_resolve_embedding_model returns None when the source has no active index."""
    source = _make_source(active_physical_index_id=None)
    session = MagicMock()

    assert _resolve_embedding_model(source, session) is None


def test_resolve_embedding_model_no_embedding_in_recipe():
    """_resolve_embedding_model returns None when the recipe lacks embedding config."""
    from retrieval_hub.models import PhysicalIndex as PIModel
    from retrieval_hub.models import RecipeVersion as RVModel

    source = _make_source()
    pi = _make_physical_index()
    rv = _make_recipe_version(content={"parser": "docling"})

    session = MagicMock()

    def mock_query(model):
        if model is PIModel:
            return _MockQuery(pi)
        if model is RVModel:
            return _MockQuery(rv)
        return _MockQuery(None)

    session.query.side_effect = mock_query

    assert _resolve_embedding_model(source, session) is None


# ---------------------------------------------------------------------------
# _parse_source_slugs
# ---------------------------------------------------------------------------


def test_parse_source_slugs_single():
    """Single slug returns a one-element list without touching the session."""
    session = MagicMock()
    assert _parse_source_slugs("va-cpg", session) == ["va-cpg"]
    session.query.assert_not_called()


def test_parse_source_slugs_comma_separated():
    """Comma-separated slugs are split and stripped."""
    session = MagicMock()
    result = _parse_source_slugs("va-cpg, pubmed-hypertension , aircraft", session)
    assert result == ["va-cpg", "pubmed-hypertension", "aircraft"]
    session.query.assert_not_called()


def test_parse_source_slugs_star():
    """'*' queries all sources with active physical indexes."""
    from retrieval_hub.models import Source as SModel

    source_a = _make_source(slug="src-a", active_physical_index_id="pi-a")
    source_b = _make_source(slug="src-b", active_physical_index_id="pi-b")

    session = MagicMock()
    q = MagicMock()
    q.filter.return_value = q
    q.all.return_value = [source_a, source_b]
    session.query.return_value = q

    result = _parse_source_slugs("*", session)
    assert set(result) == {"src-a", "src-b"}
    session.query.assert_called_once_with(SModel)


# ---------------------------------------------------------------------------
# retrieve — multi-source federated search
# ---------------------------------------------------------------------------


def _make_multi_source_session(sources, *, rv_map=None):
    """Build a mock session for multi-source retrieve tests.

    Handles the per-slug Source lookups in the per_source_metadata loop
    and the PhysicalIndex/RecipeVersion lookups from _resolve_embedding_model.

    Parameters:
        sources: list of source SimpleNamespace objects
        rv_map: optional dict of slug -> RecipeVersion; if None, uses a
                default RecipeVersion with model="test-model" for all sources
    """
    from retrieval_hub.models import PhysicalIndex as PIModel
    from retrieval_hub.models import RecipeVersion as RVModel
    from retrieval_hub.models import Source as SModel

    pi = _make_physical_index()
    if rv_map is None:
        rv_default = _make_recipe_version(
            content={"embedding": {"model": "test-model"}},
        )
        rv_map = {s.slug: rv_default for s in sources}

    slug_to_source = {s.slug: s for s in sources}
    source_iter = iter(sources)

    session = MagicMock()

    def mock_query(model):
        if model is SModel:
            q = MagicMock()

            def _filter(*args, **kwargs):
                fq = MagicMock()
                # Each Source filter().one_or_none() returns next source
                src = next(source_iter, None)
                fq.one_or_none.return_value = src
                # .all() is used by _parse_source_slugs("*")
                fq.all.return_value = list(sources)
                return fq

            q.filter = _filter
            return q
        if model is PIModel:
            return _MockQuery(pi)
        if model is RVModel:
            # Return the recipe version that matches the current source.
            # Since _resolve_embedding_model is called once per source in
            # slug order, we cycle through rv_map values in source order.
            q = MagicMock()

            def _rv_filter(*args, **kwargs):
                fq = MagicMock()
                # Pop the first remaining rv
                slug = next(iter(rv_map))
                fq.one_or_none.return_value = rv_map.pop(slug, None)
                return fq

            q.filter = _rv_filter
            return q
        return _MockQuery(None)

    session.query.side_effect = mock_query
    return session


@pytest.mark.asyncio
async def test_retrieve_multi_source_comma_separated():
    """Comma-separated source slugs trigger federated search with RRF merge."""
    hit_a = SimpleNamespace(
        chunk_id="a1", text="Source A hit", score=1 / 61,
        doc_title="Doc A", doc_url="https://a.com",
        doc_section="Sec 1", chunk_index=0, source_slug="src-a",
        request_id="req-1",
    )
    hit_b = SimpleNamespace(
        chunk_id="b1", text="Source B hit", score=1 / 61,
        doc_title="Doc B", doc_url="https://b.com",
        doc_section="Sec 2", chunk_index=0, source_slug="src-b",
        request_id="req-1",
    )

    source_a = _make_source(slug="src-a", name="Source A")
    source_b = _make_source(slug="src-b", name="Source B")
    session = _make_multi_source_session([source_a, source_b])

    with patch(
        "retrieval_hub_mcp.server.retrieval_multi_query",
        return_value={"src-a": [hit_a], "src-b": [hit_b]},
    ), patch(
        "retrieval_hub_mcp.server.rrf_merge",
        return_value=[hit_a, hit_b],
    ):
        resp = await retrieve(
            query="test query",
            source="src-a,src-b",
            top_k=5,
            session=session,
        )

    assert isinstance(resp, RetrievalResponse)
    assert len(resp.hits) == 2
    assert resp.hits[0].source_slug == "src-a"
    assert resp.hits[1].source_slug == "src-b"
    # Multi-source: top-level fields are null, metadata in per_source_metadata
    assert resp.embedding_model is None
    assert resp.usage_rules is None
    assert resp.per_source_metadata is not None
    assert "src-a" in resp.per_source_metadata
    assert "src-b" in resp.per_source_metadata


@pytest.mark.asyncio
async def test_retrieve_star_queries_all():
    """'*' source resolves to all queryable sources via _parse_source_slugs."""
    source_a = _make_source(slug="src-a", active_physical_index_id="pi-a")
    source_b = _make_source(slug="src-b", active_physical_index_id="pi-b")

    hit = SimpleNamespace(
        chunk_id="c1", text="hit", score=1 / 61,
        doc_title="Doc", doc_url="https://x.com",
        doc_section=None, chunk_index=0, source_slug="src-a",
        request_id="req-1",
    )

    # For "*", _parse_source_slugs queries Source with active_physical_index filter.
    # Then the per_source_metadata loop queries Source again for each slug.
    # Total Source queries: 1 (parse) + 2 (metadata loop) = 3 filter() calls.
    all_sources = [source_a, source_b]
    source_iter = iter([source_a, source_b])  # for metadata loop

    from retrieval_hub.models import PhysicalIndex as PIModel
    from retrieval_hub.models import RecipeVersion as RVModel
    from retrieval_hub.models import Source as SModel

    pi = _make_physical_index()
    rv = _make_recipe_version(content={"embedding": {"model": "test-model"}})

    session = MagicMock()
    filter_call_count = [0]

    def mock_query(model):
        if model is SModel:
            q = MagicMock()

            def _filter(*args, **kwargs):
                filter_call_count[0] += 1
                fq = MagicMock()
                if filter_call_count[0] == 1:
                    # First filter call: _parse_source_slugs("*")
                    fq.all.return_value = all_sources
                else:
                    # Subsequent calls: per_source_metadata loop
                    fq.one_or_none.return_value = next(source_iter, None)
                return fq

            q.filter = _filter
            return q
        if model is PIModel:
            return _MockQuery(pi)
        if model is RVModel:
            return _MockQuery(rv)
        return _MockQuery(None)

    session.query.side_effect = mock_query

    with patch(
        "retrieval_hub_mcp.server.retrieval_multi_query",
        return_value={"src-a": [hit], "src-b": []},
    ) as mock_mq, patch(
        "retrieval_hub_mcp.server.rrf_merge",
        return_value=[hit],
    ):
        resp = await retrieve(
            query="test",
            source="*",
            top_k=5,
            session=session,
        )

    # multi_query should have been called with both slugs
    mock_mq.assert_called_once()
    called_slugs = mock_mq.call_args[1]["source_slugs"]
    assert set(called_slugs) == {"src-a", "src-b"}
    assert isinstance(resp, RetrievalResponse)
    assert resp.per_source_metadata is not None


@pytest.mark.asyncio
async def test_retrieve_single_source_still_works():
    """A single source slug (no commas) uses the existing single-source path."""
    mock_results = [_make_retrieval_result()]
    source = _make_source()
    session = _make_retrieve_session(source)

    with patch(
        "retrieval_hub_mcp.server.retrieval_query",
        return_value=mock_results,
    ) as mock_q:
        resp = await retrieve(
            query="test query",
            source="test-source",
            top_k=5,
            session=session,
        )

    # Single source uses retrieval_query, not retrieval_multi_query
    mock_q.assert_called_once()
    assert isinstance(resp, RetrievalResponse)
    assert len(resp.hits) == 1
    assert resp.embedding_model == "test-embed-model"
    # per_source_metadata is None for single source
    assert resp.per_source_metadata is None


@pytest.mark.asyncio
async def test_retrieve_multi_source_per_source_metadata():
    """Multi-source response carries per-source usage_rules and embedding_model."""
    source_a = _make_source(
        slug="src-a",
        name="Source A",
        usage_rules={
            "citation": "Cite source A",
            "data_freshness": {
                "source_name": "Source A",
                "last_refreshed": "2026-01-01",
            },
        },
    )
    source_b = _make_source(
        slug="src-b",
        name="Source B",
        usage_rules={"citation": "Cite source B"},
    )

    rv_a = _make_recipe_version(content={"embedding": {"model": "model-a"}})
    rv_b = _make_recipe_version(content={"embedding": {"model": "model-b"}})

    session = _make_multi_source_session(
        [source_a, source_b],
        rv_map={"src-a": rv_a, "src-b": rv_b},
    )

    hit = SimpleNamespace(
        chunk_id="c1", text="hit", score=1 / 61,
        doc_title="Doc", doc_url="https://x.com",
        doc_section=None, chunk_index=0, source_slug="src-a",
        request_id="req-1",
    )

    with patch(
        "retrieval_hub_mcp.server.retrieval_multi_query",
        return_value={"src-a": [hit], "src-b": []},
    ), patch(
        "retrieval_hub_mcp.server.rrf_merge",
        return_value=[hit],
    ):
        resp = await retrieve(
            query="test",
            source="src-a,src-b",
            top_k=5,
            session=session,
        )

    assert resp.per_source_metadata is not None
    meta_a = resp.per_source_metadata.get("src-a")
    assert meta_a is not None
    assert isinstance(meta_a, SourceRetrievalMetadata)
    assert meta_a.embedding_model == "model-a"
    assert meta_a.usage_rules is not None
    assert meta_a.usage_rules.citation == "Cite source A"
    assert meta_a.data_freshness is not None
    assert meta_a.data_freshness.last_refreshed == "2026-01-01"

    meta_b = resp.per_source_metadata.get("src-b")
    assert meta_b is not None
    assert meta_b.embedding_model == "model-b"
    assert meta_b.usage_rules is not None
    assert meta_b.usage_rules.citation == "Cite source B"
    # Source B has no data_freshness
    assert meta_b.data_freshness is None


@pytest.mark.asyncio
async def test_retrieve_file_path_rejects_multi_source():
    """file_path with comma-separated sources raises ToolError."""
    session = MagicMock()
    # _parse_source_slugs for "src-a,src-b" does not query the session,
    # but file_path guard checks len(slugs) before touching session further.

    with pytest.raises(ToolError, match="file_path requires a single source"):
        await retrieve(
            query="unused",
            source="src-a,src-b",
            file_path="some/file.py",
            session=session,
        )


@pytest.mark.asyncio
async def test_retrieve_multi_source_empty_merge():
    """Multi-source with no results from any source returns empty hits."""
    source_a = _make_source(slug="src-a")
    source_b = _make_source(slug="src-b")
    session = _make_multi_source_session([source_a, source_b])

    with patch(
        "retrieval_hub_mcp.server.retrieval_multi_query",
        return_value={"src-a": [], "src-b": []},
    ), patch(
        "retrieval_hub_mcp.server.rrf_merge",
        return_value=[],
    ):
        resp = await retrieve(
            query="obscure query",
            source="src-a,src-b",
            top_k=5,
            session=session,
        )

    assert isinstance(resp, RetrievalResponse)
    assert len(resp.hits) == 0
    assert resp.request_id  # should still have a UUID
