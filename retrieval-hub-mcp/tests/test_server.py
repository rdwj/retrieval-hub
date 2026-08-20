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
from retrieval_hub_mcp.schemas import (
    RefineHit,
    RefineResponse,
    RetrievalHit,
    RetrievalResponse,
    SourceDetail,
    SourceSummary,
)
from retrieval_hub_mcp.server import describe_source, list_sources, refine, retrieve

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
    )


def _make_physical_index(
    id="pi-001",
    document_count=42,
    build_metadata=None,
):
    return SimpleNamespace(
        id=id,
        document_count=document_count,
        build_metadata=build_metadata,
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
    rv = _make_recipe_version()
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
            # RecipeVersion lookup
            return _MockQuery(rv)
        elif call_count == 4:
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
    assert result.recipe_content == {"parser": "docling", "chunker": "recursive"}
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
async def test_describe_source_no_recipe_or_prompts():
    """describe_source handles sources with no recipe or sample prompts."""
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

    assert result.recipe_content is None
    assert result.sample_prompts is None
    assert result.document_count is None
    assert result.chunk_count is None


# ---------------------------------------------------------------------------
# Retrieve session helpers
# ---------------------------------------------------------------------------


def _make_retrieve_session(source=None):
    """Build a mock session that returns *source* from the Source query."""
    session = MagicMock()
    session.query.return_value = _MockQuery(source)
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
    assert resp.hits[0].text == "Relevant passage text"
    assert resp.hits[0].score == 0.92
    assert resp.hits[0].doc_title == "Manual v3"
    assert resp.hits[0].doc_url == "https://example.com/manual-v3"
    assert resp.hits[0].doc_section == "Chapter 2"
    assert resp.hits[0].chunk_index == 0
    assert resp.hits[0].physical_index_id == "pi-001"
    assert resp.hits[0].recipe_version == 1
    assert resp.hits[0].request_id == "req-abc"

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
    assert resp.hits[0].physical_index_id == "github-live"


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
    assert resp.hits[0].recipe_version == 0


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


@pytest.mark.asyncio
async def test_refine_returns_adjacent_chunks():
    """refine delegates to retrieval_refine and maps results to RefineResponse."""
    mock_results = [
        _make_refine_result(text="before", chunk_index=4),
        _make_refine_result(text="target", chunk_index=5),
        _make_refine_result(text="after", chunk_index=6),
    ]

    source = _make_source()
    session = _make_retrieve_session(source)

    with patch("retrieval_hub_mcp.server.retrieval_refine", return_value=mock_results):
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
    assert resp.strategy == "adjacent"
    assert len(resp.chunks) == 3
    assert isinstance(resp.chunks[0], RefineHit)
    assert resp.chunks[0].text == "before"
    assert resp.chunks[0].is_origin is False
    assert not hasattr(resp.chunks[0], "doc_title")
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
async def test_refine_passes_window():
    """refine forwards the window parameter to retrieval_refine."""
    source = _make_source()
    session = _make_retrieve_session(source)
    mock_results = [_make_refine_result(chunk_index=3)]

    with patch(
        "retrieval_hub_mcp.server.retrieval_refine", return_value=mock_results
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
    )


@pytest.mark.asyncio
async def test_refine_empty_result_raises_tool_error():
    """refine raises ToolError with actionable guidance when no chunks are found."""
    from fastmcp.exceptions import ToolError

    source = _make_source()
    session = _make_retrieve_session(source)

    with patch("retrieval_hub_mcp.server.retrieval_refine", return_value=[]):
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

    with patch("retrieval_hub_mcp.server.retrieval_refine", return_value=mock_results):
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
