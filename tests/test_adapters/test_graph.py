"""Tests for the GraphAdapter.

We mock the neo4j driver and psycopg connections so the tests run without
a live Memgraph or PostgreSQL instance. The goal is to verify strategy
validation, relationship rendering, and chunk-fetching wiring.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from retrieval_hub.adapters.graph import GraphAdapter
from retrieval_hub.models import PhysicalIndex, RecipeVersion, Source
from retrieval_hub.models.enums import (
    AccessVisibility,
    IndexHealth,
    PhysicalIndexBackend,
    SourceFamily,
    SourceStatus,
)


# ---------------------------------------------------------------------------
# Factories (mirrors test_document.py patterns)
# ---------------------------------------------------------------------------


def _make_source() -> Source:
    return Source(
        id="src_graph01",
        slug="test-graph",
        name="Test Graph Source",
        family=SourceFamily.GRAPH,
        status=SourceStatus.CURATED,
        visibility=AccessVisibility.PUBLIC,
        description_short="graph source for tests",
        owner_team="tests",
        owner_contacts=[],
        maintainers=[],
        rewriter_metadata={"enabled": False},
        agent_write_policy={"allowed": False},
        access={"visibility": "public"},
        lineage_origin={},
        refresh_cadence="on_demand",
    )


def _make_recipe_version() -> RecipeVersion:
    return RecipeVersion(
        id="rcv_graph01",
        source_id="src_graph01",
        version_number=1,
        content={"embedding": {"model": "fake-model", "dimension": 768}},
    )


def _make_physical_index(location: str = "idx_graph_test") -> PhysicalIndex:
    return PhysicalIndex(
        id="pidx_graph01",
        source_id="src_graph01",
        recipe_version_id="rcv_graph01",
        backend_kind=PhysicalIndexBackend.PGVECTOR,
        location=location,
        health=IndexHealth.OK,
        document_count=10,
        build_metadata={},
    )


def _make_adapter(
    *,
    location: str = "idx_graph_test",
    bolt_uri: str = "bolt://mock:7687",
) -> GraphAdapter:
    return GraphAdapter(
        source=_make_source(),
        physical_index=_make_physical_index(location),
        recipe_version=_make_recipe_version(),
        vectors_db_url="postgresql+psycopg://retrievalhub:pw@localhost:5433/rv",
        memgraph_bolt_uri=bolt_uri,
    )


# ---------------------------------------------------------------------------
# Strategy validation
# ---------------------------------------------------------------------------


def test_strategy_validation_rejects_adjacent() -> None:
    """GraphAdapter only supports 'graph_traverse_from_seed'."""
    adapter = _make_adapter()

    with pytest.raises(ValueError, match="does not support the 'adjacent' strategy"):
        adapter.refine(
            doc_title="n1",
            chunk_index=0,
            query="test",
            window=1,
            request_id="req-1",
            strategy="adjacent",
        )


def test_strategy_validation_rejects_section() -> None:
    adapter = _make_adapter()

    with pytest.raises(ValueError, match="does not support the 'section' strategy"):
        adapter.refine(
            doc_title="n1",
            chunk_index=0,
            query="test",
            window=1,
            request_id="req-1",
            strategy="section",
        )


def test_strategy_validation_accepts_graph_traverse() -> None:
    """graph_traverse_from_seed passes validation (may fail on Memgraph query)."""
    adapter = _make_adapter()

    # Mock the driver so we don't need a live Memgraph.
    mock_session = MagicMock()
    mock_session.run.return_value = iter([])  # empty results
    mock_driver = MagicMock()
    mock_driver.session.return_value.__enter__ = MagicMock(return_value=mock_session)
    mock_driver.session.return_value.__exit__ = MagicMock(return_value=False)

    adapter._driver = mock_driver

    # Should not raise ValueError (the query runs against the mock and
    # returns empty results, producing an empty RefineOutput).
    result = adapter.refine(
        doc_title="n1",
        chunk_index=0,
        query="test",
        window=2,
        request_id="req-2",
        strategy="graph_traverse_from_seed",
    )

    assert result.results == []
    assert result.truncated is False


# ---------------------------------------------------------------------------
# _render_with_relationships
# ---------------------------------------------------------------------------


def test_render_with_relationships() -> None:
    adapter = _make_adapter()

    rel_records = [
        {
            "src": "n1",
            "rel_type": "CtD",
            "tgt": "n2",
            "tgt_name": "Migraine",
            "tgt_type": "Disease",
            "edge_src": "n1",
        },
        {
            "src": "n1",
            "rel_type": "CbG",
            "tgt": "g1",
            "tgt_name": "COX2",
            "tgt_type": "Gene",
            "edge_src": "n1",
        },
        {
            "src": "n1",
            "rel_type": "DaG",
            "tgt": "n1",
            "tgt_name": "IL6",
            "tgt_type": "Gene",
            "edge_src": "g2",  # incoming edge
        },
    ]

    text = adapter._render_with_relationships(
        seed_id="n1",
        seed_name="Aspirin",
        seed_type="Compound",
        rel_records=rel_records,
        max_tokens=2048,
    )

    assert "Seed: Aspirin (Compound, n1)" in text
    # Outbound edges use -->
    assert "--[CtD]--> Migraine (Disease)" in text
    assert "--[CbG]--> COX2 (Gene)" in text
    # Inbound edge uses <--
    assert "<--[DaG]-- IL6 (Gene)" in text


def test_render_with_relationships_token_budget() -> None:
    """With a small token budget, the output is truncated."""
    adapter = _make_adapter()

    # Generate enough relationship records to exceed a tiny budget.
    rel_records = [
        {
            "src": "n1",
            "rel_type": f"REL_{i}",
            "tgt": f"t{i}",
            "tgt_name": f"Target_{i}",
            "tgt_type": "Entity",
            "edge_src": "n1",
        }
        for i in range(50)
    ]

    text = adapter._render_with_relationships(
        seed_id="n1",
        seed_name="CentralNode",
        seed_type="Hub",
        rel_records=rel_records,
        max_tokens=30,  # very tight budget
    )

    assert "Seed: CentralNode" in text
    assert "truncated at 30 tokens" in text
    # Not all 50 relationships should appear.
    lines = text.strip().split("\n")
    assert len(lines) < 52  # seed + 50 rels + truncation msg


# ---------------------------------------------------------------------------
# _fetch_neighbor_chunks
# ---------------------------------------------------------------------------


def test_fetch_neighbor_chunks_empty() -> None:
    """Empty entity_ids list produces empty result, no DB call."""
    adapter = _make_adapter()

    result = adapter._fetch_neighbor_chunks([], request_id="req-empty")

    assert result == []


def test_fetch_neighbor_chunks_returns_results() -> None:
    """Mocked DB returns rows converted to RetrievalResult objects."""
    adapter = _make_adapter(location="idx_graph_tbl")

    fake_cursor = MagicMock()
    col_names = [
        "id", "chunk_text", "chunk_tokens", "doc_title",
        "doc_url", "doc_section", "chunk_index",
    ]
    fake_cursor.description = [MagicMock(name=n) for n in col_names]
    for col, name in zip(fake_cursor.description, col_names, strict=True):
        col.name = name
    fake_cursor.fetchall.return_value = [
        ("uuid-1", "Aspirin is a compound.", 12, "n1", "graph://test/n1", "Compound", 0),
        ("uuid-2", "Migraine is a disease.", 11, "n2", "graph://test/n2", "Disease", 1),
    ]

    fake_conn = MagicMock()
    fake_conn.cursor.return_value.__enter__ = MagicMock(return_value=fake_cursor)
    fake_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)

    fake_connect_ctx = MagicMock()
    fake_connect_ctx.__enter__ = MagicMock(return_value=fake_conn)
    fake_connect_ctx.__exit__ = MagicMock(return_value=False)

    with patch("psycopg.connect", return_value=fake_connect_ctx):
        results = adapter._fetch_neighbor_chunks(
            ["n1", "n2"], request_id="req-neigh",
        )

    assert len(results) == 2
    assert results[0].chunk_id == "uuid-1"
    assert results[0].doc_title == "n1"
    assert results[0].score == 1.0
    assert results[0].request_id == "req-neigh"
    assert results[0].physical_index_id == "pidx_graph01"
    assert results[0].recipe_version == 1
    assert results[1].chunk_id == "uuid-2"
    assert results[1].doc_title == "n2"

    # Verify SQL references the correct table.
    executed_sql = fake_cursor.execute.call_args[0][0]
    assert "idx_graph_tbl" in executed_sql
    assert "doc_title IN" in executed_sql


# ---------------------------------------------------------------------------
# Full refine traversal (integration-style with mocks)
# ---------------------------------------------------------------------------


def test_graph_traverse_refine_with_neighbors() -> None:
    """End-to-end refine: mock Memgraph returns seed + neighbors, mock pg returns chunks."""
    adapter = _make_adapter(location="idx_graph_full")

    # Mock Memgraph driver
    mock_session = MagicMock()

    # First query: seed + neighbor traversal
    traversal_records = [
        {
            "seed_id": "n1", "seed_name": "Aspirin", "seed_type": "Compound",
            "neighbor_id": "n2", "neighbor_name": "Migraine", "neighbor_type": "Disease",
        },
        {
            "seed_id": "n1", "seed_name": "Aspirin", "seed_type": "Compound",
            "neighbor_id": "n3", "neighbor_name": "COX2", "neighbor_type": "Gene",
        },
    ]

    # Second query: relationship details
    rel_records = [
        {
            "src": "n1", "rel_type": "CtD", "tgt": "n2",
            "tgt_name": "Migraine", "tgt_type": "Disease", "edge_src": "n1",
        },
    ]

    # Mock session.run to return different results for traversal vs relationship queries
    call_count = 0

    def mock_run(cypher, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return iter(traversal_records)
        return iter(rel_records)

    mock_session.run = mock_run
    mock_driver = MagicMock()
    mock_driver.session.return_value.__enter__ = MagicMock(return_value=mock_session)
    mock_driver.session.return_value.__exit__ = MagicMock(return_value=False)
    adapter._driver = mock_driver

    # Mock pgvector for _fetch_neighbor_chunks
    fake_cursor = MagicMock()
    col_names = [
        "id", "chunk_text", "chunk_tokens", "doc_title",
        "doc_url", "doc_section", "chunk_index",
    ]
    fake_cursor.description = [MagicMock(name=n) for n in col_names]
    for col, name in zip(fake_cursor.description, col_names, strict=True):
        col.name = name
    fake_cursor.fetchall.return_value = [
        ("uuid-2", "Migraine text", 50, "n2", "graph://test/n2", "Disease", 1),
        ("uuid-3", "COX2 text", 50, "n3", "graph://test/n3", "Gene", 2),
    ]
    fake_conn = MagicMock()
    fake_conn.cursor.return_value.__enter__ = MagicMock(return_value=fake_cursor)
    fake_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
    fake_connect_ctx = MagicMock()
    fake_connect_ctx.__enter__ = MagicMock(return_value=fake_conn)
    fake_connect_ctx.__exit__ = MagicMock(return_value=False)

    with patch("psycopg.connect", return_value=fake_connect_ctx):
        output = adapter.refine(
            doc_title="n1",
            chunk_index=0,
            query="What treats migraine?",
            window=2,
            request_id="req-traverse",
            strategy="graph_traverse_from_seed",
        )

    assert len(output.results) == 2
    assert output.results[0].doc_title == "n2"
    assert output.results[1].doc_title == "n3"
    assert all(r.request_id == "req-traverse" for r in output.results)
