"""Tests for the RetrievalHub MCP server tools.

Each test constructs mock dependencies (database session, retrieval function)
and calls the tool functions directly, bypassing FastMCP's dependency injection
layer. This validates the business logic without requiring a running database
or MCP transport.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from retrieval_hub_mcp.schemas import RetrievalHit, SourceDetail, SourceSummary
from retrieval_hub_mcp.server import describe_source, list_sources, retrieve


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
# retrieve
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

    session = MagicMock()

    with patch("retrieval_hub_mcp.server.retrieval_query", return_value=mock_results):
        results = await retrieve(
            query="test query",
            source="test-source",
            top_k=5,
            session=session,
        )

    assert len(results) == 2
    assert isinstance(results[0], RetrievalHit)
    assert results[0].text == "Relevant passage text"
    assert results[0].score == 0.92
    assert results[0].doc_title == "Manual v3"
    assert results[0].doc_url == "https://example.com/manual-v3"
    assert results[0].doc_section == "Chapter 2"
    assert results[0].physical_index_id == "pi-001"
    assert results[0].recipe_version == 1
    assert results[0].request_id == "req-abc"

    assert results[1].doc_section is None


@pytest.mark.asyncio
async def test_retrieve_source_not_found():
    """retrieve raises ToolError when the source slug doesn't exist."""
    from retrieval_hub.retrieval.api import SourceNotFoundError
    from fastmcp.exceptions import ToolError

    session = MagicMock()

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
    from retrieval_hub.retrieval.api import SourceNotQueryableError
    from fastmcp.exceptions import ToolError

    session = MagicMock()

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
    from retrieval_hub.retrieval.api import UnsupportedFamilyError
    from fastmcp.exceptions import ToolError

    session = MagicMock()

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
    session = MagicMock()

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
