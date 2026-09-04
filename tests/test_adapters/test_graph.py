"""Tests for the GraphAdapter.

We mock the neo4j driver and psycopg connections so the tests run without
a live Memgraph or PostgreSQL instance. The goal is to verify strategy
validation, relationship rendering, and chunk-fetching wiring.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from retrieval_hub.adapters.graph import GraphAdapter, _normalize_edge_type
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


# ---------------------------------------------------------------------------
# Edge type normalization
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Compound___treats___Disease", "Compound___treats___Disease"),
        ("Compound - treats - Disease", "Compound___treats___Disease"),
        ("Gene > participates > Pathway", "Gene___participates___Pathway"),
        ("simple_rel", "simple_rel"),
        ("A - B - C - D - E", "A___B___C___D___E"),
    ],
)
def test_normalize_edge_type(raw: str, expected: str) -> None:
    assert _normalize_edge_type(raw) == expected


# ---------------------------------------------------------------------------
# edge_types filtering
# ---------------------------------------------------------------------------


def test_graph_traverse_with_edge_types() -> None:
    """Traversal with edge_types passes normalized types to the Cypher query."""
    adapter = _make_adapter(location="idx_graph_et")

    mock_session = MagicMock()
    captured_calls: list[dict] = []

    traversal_records = [
        {
            "seed_id": "n1", "seed_name": "Aspirin", "seed_type": "Compound",
            "neighbor_id": "n2", "neighbor_name": "Migraine", "neighbor_type": "Disease",
        },
    ]
    rel_records = [
        {
            "src": "n1", "rel_type": "Compound___treats___Disease", "tgt": "n2",
            "tgt_name": "Migraine", "tgt_type": "Disease", "edge_src": "n1",
        },
    ]

    call_count = 0

    def mock_run(cypher, **kwargs):
        nonlocal call_count
        captured_calls.append({"cypher": cypher, "kwargs": kwargs})
        call_count += 1
        if call_count == 1:
            return iter(traversal_records)
        return iter(rel_records)

    mock_session.run = mock_run
    mock_driver = MagicMock()
    mock_driver.session.return_value.__enter__ = MagicMock(return_value=mock_session)
    mock_driver.session.return_value.__exit__ = MagicMock(return_value=False)
    adapter._driver = mock_driver

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
            request_id="req-et",
            strategy="graph_traverse_from_seed",
            edge_types=["Compound - treats - Disease"],
        )

    assert len(output.results) == 1
    assert output.results[0].doc_title == "n2"

    # Verify the traversal Cypher used $edge_types and the path pattern
    traversal_cypher = captured_calls[0]["cypher"]
    assert "$edge_types" in traversal_cypher
    assert "ALL(rel IN relationships(p)" in traversal_cypher
    assert captured_calls[0]["kwargs"]["edge_types"] == [
        "Compound___treats___Disease",
    ]

    # Verify the relationship Cypher also filtered by edge_types
    rel_cypher = captured_calls[1]["cypher"]
    assert "type(r) IN $edge_types" in rel_cypher
    assert captured_calls[1]["kwargs"]["edge_types"] == [
        "Compound___treats___Disease",
    ]


# ---------------------------------------------------------------------------
# max_nodes limiting
# ---------------------------------------------------------------------------


def test_graph_traverse_with_max_nodes() -> None:
    """max_nodes caps the number of neighbors returned."""
    adapter = _make_adapter(location="idx_graph_mn")

    mock_session = MagicMock()
    traversal_records = [
        {
            "seed_id": "n1", "seed_name": "Hub", "seed_type": "Compound",
            "neighbor_id": f"n{i}", "neighbor_name": f"Neighbor_{i}",
            "neighbor_type": "Entity",
        }
        for i in range(2, 12)  # 10 neighbors
    ]
    rel_records = []

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

    # pgvector returns chunks for whichever entity_ids we ask for
    fake_cursor = MagicMock()
    col_names = [
        "id", "chunk_text", "chunk_tokens", "doc_title",
        "doc_url", "doc_section", "chunk_index",
    ]
    fake_cursor.description = [MagicMock(name=n) for n in col_names]
    for col, name in zip(fake_cursor.description, col_names, strict=True):
        col.name = name
    # Return exactly 3 rows (matching max_nodes=3)
    fake_cursor.fetchall.return_value = [
        (f"uuid-{i}", f"Text {i}", 10, f"n{i}", f"graph://test/n{i}", "Entity", i)
        for i in range(2, 5)
    ]
    fake_conn = MagicMock()
    fake_conn.cursor.return_value.__enter__ = MagicMock(return_value=fake_cursor)
    fake_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
    fake_connect_ctx = MagicMock()
    fake_connect_ctx.__enter__ = MagicMock(return_value=fake_conn)
    fake_connect_ctx.__exit__ = MagicMock(return_value=False)

    with patch("psycopg.connect", return_value=fake_connect_ctx):
        adapter.refine(
            doc_title="n1",
            chunk_index=0,
            query="test",
            window=2,
            request_id="req-mn",
            strategy="graph_traverse_from_seed",
            max_nodes=3,
        )

    # Verify the SQL only queried for 3 entity IDs (n2, n3, n4)
    executed_sql_args = fake_cursor.execute.call_args[0][1]
    assert len(executed_sql_args) == 3
    assert executed_sql_args == ["n2", "n3", "n4"]


# ---------------------------------------------------------------------------
# edge_types + max_nodes combined
# ---------------------------------------------------------------------------


def test_graph_traverse_edge_types_and_max_nodes_combined() -> None:
    """Both parameters applied together: filter by type, then cap count."""
    adapter = _make_adapter(location="idx_graph_combo")

    mock_session = MagicMock()
    traversal_records = [
        {
            "seed_id": "n1", "seed_name": "Aspirin", "seed_type": "Compound",
            "neighbor_id": f"n{i}", "neighbor_name": f"Target_{i}",
            "neighbor_type": "Disease",
        }
        for i in range(2, 7)  # 5 neighbors after edge_types filter
    ]
    rel_records = []

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

    fake_cursor = MagicMock()
    col_names = [
        "id", "chunk_text", "chunk_tokens", "doc_title",
        "doc_url", "doc_section", "chunk_index",
    ]
    fake_cursor.description = [MagicMock(name=n) for n in col_names]
    for col, name in zip(fake_cursor.description, col_names, strict=True):
        col.name = name
    fake_cursor.fetchall.return_value = [
        (f"uuid-{i}", f"Text {i}", 10, f"n{i}", f"graph://test/n{i}", "Disease", i)
        for i in range(2, 4)  # 2 rows for max_nodes=2
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
            query="test",
            window=2,
            request_id="req-combo",
            strategy="graph_traverse_from_seed",
            edge_types=["Compound___treats___Disease"],
            max_nodes=2,
        )

    # Only 2 entity IDs should have been queried (capped by max_nodes)
    executed_sql_args = fake_cursor.execute.call_args[0][1]
    assert len(executed_sql_args) == 2
    assert executed_sql_args == ["n2", "n3"]

    # total_chunks reflects all 5 neighbors (before max_nodes cap),
    # because max_nodes is applied after the graph query
    # but truncated should be True since we capped
    assert output.truncated is True


# ---------------------------------------------------------------------------
# _collect_scope_ids
# ---------------------------------------------------------------------------


def test_collect_scope_ids() -> None:
    """Seed + neighbors are returned from Memgraph traversal."""
    adapter = _make_adapter()

    mock_session = MagicMock()
    records = [
        {"seed_id": "patient-1", "neighbor_id": "enc-1"},
        {"seed_id": "patient-1", "neighbor_id": "obs-1"},
        {"seed_id": "patient-1", "neighbor_id": None},  # seed with no extra neighbor
    ]
    mock_session.run.return_value = iter(records)

    mock_driver = MagicMock()
    mock_driver.session.return_value.__enter__ = MagicMock(return_value=mock_session)
    mock_driver.session.return_value.__exit__ = MagicMock(return_value=False)
    adapter._driver = mock_driver

    ids = adapter._collect_scope_ids("patient-1", hops=2)

    assert set(ids) == {"patient-1", "enc-1", "obs-1"}


def test_collect_scope_ids_no_entity() -> None:
    """When the seed entity is not found, returns empty list."""
    adapter = _make_adapter()

    mock_session = MagicMock()
    mock_session.run.return_value = iter([])  # no records

    mock_driver = MagicMock()
    mock_driver.session.return_value.__enter__ = MagicMock(return_value=mock_session)
    mock_driver.session.return_value.__exit__ = MagicMock(return_value=False)
    adapter._driver = mock_driver

    ids = adapter._collect_scope_ids("nonexistent-id", hops=2)

    assert ids == []


# ---------------------------------------------------------------------------
# Scoped retrieve
# ---------------------------------------------------------------------------


def test_retrieve_with_scope_entity_id() -> None:
    """Full scoped retrieve: Memgraph traversal + pgvector scoped search."""
    adapter = _make_adapter(location="idx_graph_scope")

    # Mock Memgraph for _collect_scope_ids
    mock_mg_session = MagicMock()
    scope_records = [
        {"seed_id": "patient-1", "neighbor_id": "enc-1"},
        {"seed_id": "patient-1", "neighbor_id": "obs-1"},
    ]
    mock_mg_session.run.return_value = iter(scope_records)

    mock_driver = MagicMock()
    mock_driver.session.return_value.__enter__ = MagicMock(return_value=mock_mg_session)
    mock_driver.session.return_value.__exit__ = MagicMock(return_value=False)
    adapter._driver = mock_driver

    # Mock QueryEmbedder
    mock_embedder = MagicMock()
    mock_embedder.embed.return_value = [0.1] * 768

    # Mock pgvector for _scoped_similarity_search
    fake_cursor = MagicMock()
    col_names = [
        "id", "chunk_text", "doc_title", "doc_url",
        "doc_section", "chunk_index", "score",
    ]
    fake_cursor.description = [MagicMock(name=n) for n in col_names]
    for col, name in zip(fake_cursor.description, col_names, strict=True):
        col.name = name
    fake_cursor.fetchall.return_value = [
        ("uuid-1", "Patient data", "patient-1", "", "Patient", 0, 0.92),
        ("uuid-2", "Encounter data", "enc-1", "", "Encounter", 0, 0.88),
    ]

    fake_conn = MagicMock()
    fake_conn.cursor.return_value.__enter__ = MagicMock(return_value=fake_cursor)
    fake_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
    fake_connect_ctx = MagicMock()
    fake_connect_ctx.__enter__ = MagicMock(return_value=fake_conn)
    fake_connect_ctx.__exit__ = MagicMock(return_value=False)

    with (
        patch(
            "retrieval_hub.ingestion.embed.QueryEmbedder",
            return_value=mock_embedder,
        ),
        patch("psycopg.connect", return_value=fake_connect_ctx),
        patch("pgvector.psycopg.register_vector"),
    ):
        results = adapter.retrieve(
            "What observations exist?",
            top_k=5,
            request_id="req-scope",
            scope_entity_id="patient-1",
        )

    assert len(results) == 2
    assert results[0].chunk_id == "uuid-1"
    assert results[0].doc_title == "patient-1"
    assert results[0].score == pytest.approx(0.92)
    assert results[0].request_id == "req-scope"
    assert results[1].chunk_id == "uuid-2"
    assert results[1].doc_title == "enc-1"

    # Verify SQL contained the scope filter
    executed_sql = fake_cursor.execute.call_args[0][0]
    assert "doc_title = ANY(%s)" in executed_sql
    assert "idx_graph_scope" in executed_sql


def test_retrieve_without_scope_entity_id() -> None:
    """Without scope_entity_id, delegates to parent DocumentAdapter.retrieve()."""
    adapter = _make_adapter()

    with patch.object(
        adapter.__class__.__bases__[0],  # DocumentAdapter
        "retrieve",
        return_value=[],
    ) as mock_parent:
        results = adapter.retrieve(
            "some query",
            top_k=5,
            request_id="req-noscope",
        )

    assert results == []
    mock_parent.assert_called_once_with(
        "some query",
        top_k=5,
        request_id="req-noscope",
        doc_section=None,
    )


def test_retrieve_with_scope_and_doc_section() -> None:
    """Both scope_entity_id and doc_section filters are applied together."""
    adapter = _make_adapter(location="idx_graph_both")

    # Mock Memgraph
    mock_mg_session = MagicMock()
    scope_records = [
        {"seed_id": "patient-1", "neighbor_id": "obs-1"},
    ]
    mock_mg_session.run.return_value = iter(scope_records)

    mock_driver = MagicMock()
    mock_driver.session.return_value.__enter__ = MagicMock(return_value=mock_mg_session)
    mock_driver.session.return_value.__exit__ = MagicMock(return_value=False)
    adapter._driver = mock_driver

    # Mock QueryEmbedder
    mock_embedder = MagicMock()
    mock_embedder.embed.return_value = [0.1] * 768

    # Mock pgvector
    fake_cursor = MagicMock()
    col_names = [
        "id", "chunk_text", "doc_title", "doc_url",
        "doc_section", "chunk_index", "score",
    ]
    fake_cursor.description = [MagicMock(name=n) for n in col_names]
    for col, name in zip(fake_cursor.description, col_names, strict=True):
        col.name = name
    fake_cursor.fetchall.return_value = [
        ("uuid-obs", "Observation data", "obs-1", "", "Observation", 0, 0.85),
    ]

    fake_conn = MagicMock()
    fake_conn.cursor.return_value.__enter__ = MagicMock(return_value=fake_cursor)
    fake_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
    fake_connect_ctx = MagicMock()
    fake_connect_ctx.__enter__ = MagicMock(return_value=fake_conn)
    fake_connect_ctx.__exit__ = MagicMock(return_value=False)

    with (
        patch(
            "retrieval_hub.ingestion.embed.QueryEmbedder",
            return_value=mock_embedder,
        ),
        patch("psycopg.connect", return_value=fake_connect_ctx),
        patch("pgvector.psycopg.register_vector"),
    ):
        results = adapter.retrieve(
            "lab results",
            top_k=5,
            request_id="req-both",
            scope_entity_id="patient-1",
            doc_section=["Observation"],
        )

    assert len(results) == 1
    assert results[0].doc_section == "Observation"

    # Verify SQL has both filters
    executed_sql = fake_cursor.execute.call_args[0][0]
    assert "doc_title = ANY(%s)" in executed_sql
    assert "doc_section = ANY(%s)" in executed_sql


def test_retrieve_scope_entity_id_no_neighbors_returns_empty() -> None:
    """When the seed entity has no graph presence, returns empty list."""
    adapter = _make_adapter()

    mock_mg_session = MagicMock()
    mock_mg_session.run.return_value = iter([])

    mock_driver = MagicMock()
    mock_driver.session.return_value.__enter__ = MagicMock(return_value=mock_mg_session)
    mock_driver.session.return_value.__exit__ = MagicMock(return_value=False)
    adapter._driver = mock_driver

    results = adapter.retrieve(
        "any query",
        top_k=5,
        request_id="req-empty-scope",
        scope_entity_id="nonexistent-patient",
    )

    assert results == []
