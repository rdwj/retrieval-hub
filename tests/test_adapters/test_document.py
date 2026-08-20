"""Tests for the DocumentAdapter.

We mock both the ``QueryEmbedder`` and the underlying psycopg connection so
the test doesn't need sentence-transformers or a running pgvector. The goal
is to verify the wiring between adapter, embedder, SQL, and result rendering.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from retrieval_hub.adapters.document import DocumentAdapter
from retrieval_hub.models import PhysicalIndex, RecipeVersion, Source
from retrieval_hub.models.enums import (
    AccessVisibility,
    IndexHealth,
    PhysicalIndexBackend,
    SourceFamily,
    SourceStatus,
)


def _make_source() -> Source:
    return Source(
        id="src_test01",
        slug="test-source",
        name="Test Source",
        family=SourceFamily.DOCUMENT,
        status=SourceStatus.CURATED,
        visibility=AccessVisibility.PUBLIC,
        description_short="test",
        owner_team="tests",
        owner_contacts=[],
        maintainers=[],
        rewriter_metadata={"enabled": False},
        agent_write_policy={"allowed": False},
        access={"visibility": "public"},
        lineage_origin={},
        refresh_cadence="on_demand",
    )


def _make_recipe_version(content: dict) -> RecipeVersion:
    return RecipeVersion(
        id="rcv_test01",
        source_id="src_test01",
        version_number=1,
        content=content,
    )


def _make_physical_index(location: str) -> PhysicalIndex:
    return PhysicalIndex(
        id="pidx_test01",
        source_id="src_test01",
        recipe_version_id="rcv_test01",
        backend_kind=PhysicalIndexBackend.PGVECTOR,
        location=location,
        health=IndexHealth.OK,
        document_count=10,
        build_metadata={},
    )


def test_document_adapter_rejects_non_pgvector_backend() -> None:
    source = _make_source()
    recipe = _make_recipe_version({"embedding": {"model": "m", "dimension": 768}})

    bad_index = PhysicalIndex(
        id="pidx_bad",
        source_id="src_test01",
        recipe_version_id="rcv_test01",
        backend_kind="not_pgvector",  # type: ignore[arg-type]
        location="nowhere",
        health=IndexHealth.OK,
        document_count=0,
        build_metadata={},
    )

    with pytest.raises(ValueError, match="pgvector-backed"):
        DocumentAdapter(
            source=source,
            physical_index=bad_index,
            recipe_version=recipe,
            vectors_db_url="postgresql+psycopg://ignored",
        )


def test_document_adapter_retrieve_wires_embedder_and_sql() -> None:
    source = _make_source()
    recipe = _make_recipe_version(
        {"embedding": {"model": "fake-model", "dimension": 768}}
    )
    index = _make_physical_index("idx_test_table")

    adapter = DocumentAdapter(
        source=source,
        physical_index=index,
        recipe_version=recipe,
        vectors_db_url="postgresql+psycopg://retrievalhub:pw@localhost:5433/rv",
    )

    # Mock the embedder.
    fake_embedder = MagicMock()
    fake_embedder.embed.return_value = [0.1] * 768

    # Mock psycopg connection + cursor with two rows.
    fake_cursor = MagicMock()
    fake_cursor.description = [
        MagicMock(name="id"),
        MagicMock(name="chunk_text"),
        MagicMock(name="doc_title"),
        MagicMock(name="doc_url"),
        MagicMock(name="doc_section"),
        MagicMock(name="chunk_index"),
        MagicMock(name="score"),
    ]
    # Set the .name attribute on each Column mock so the adapter can read it.
    for col, name in zip(
        fake_cursor.description,
        ["id", "chunk_text", "doc_title", "doc_url", "doc_section", "chunk_index", "score"],
        strict=True,
    ):
        col.name = name
    fake_cursor.fetchall.return_value = [
        ("chunk-uuid-1", "first hit text", "Doc One", "https://example/1", "intro", 0, 0.92),
        ("chunk-uuid-2", "second hit text", "Doc Two", "https://example/2", None, 3, 0.87),
    ]
    fake_conn = MagicMock()
    fake_conn.cursor.return_value.__enter__.return_value = fake_cursor
    fake_conn.cursor.return_value.__exit__.return_value = False

    fake_connect_ctx = MagicMock()
    fake_connect_ctx.__enter__.return_value = fake_conn
    fake_connect_ctx.__exit__.return_value = False

    with (
        patch(
            "retrieval_hub.ingestion.embed.QueryEmbedder",
            return_value=fake_embedder,
        ),
        patch("psycopg.connect", return_value=fake_connect_ctx),
        patch("pgvector.psycopg.register_vector"),
    ):
        results = adapter.retrieve("test query", top_k=5, request_id="req-abc")

    assert len(results) == 2
    first = results[0]
    assert first.text == "first hit text"
    assert first.score == pytest.approx(0.92)
    assert first.doc_title == "Doc One"
    assert first.doc_url == "https://example/1"
    assert first.doc_section == "intro"
    assert first.chunk_index == 0
    # Every result must carry the full lineage handle.
    assert first.physical_index_id == index.id
    assert first.recipe_version == recipe.version_number
    assert first.request_id == "req-abc"

    second = results[1]
    assert second.doc_section is None
    assert second.chunk_index == 3
    assert second.score == pytest.approx(0.87)


def test_document_adapter_refine_fetches_adjacent_chunks() -> None:
    source = _make_source()
    recipe = _make_recipe_version(
        {"embedding": {"model": "fake-model", "dimension": 768}}
    )
    index = _make_physical_index("idx_test_table")

    adapter = DocumentAdapter(
        source=source,
        physical_index=index,
        recipe_version=recipe,
        vectors_db_url="postgresql+psycopg://retrievalhub:pw@localhost:5433/rv",
    )

    col_names = ["id", "chunk_text", "chunk_tokens", "doc_title", "doc_url", "doc_section", "chunk_index"]
    fake_cursor = MagicMock()
    fake_cursor.description = [MagicMock(name=n) for n in col_names]
    for col, name in zip(fake_cursor.description, col_names, strict=True):
        col.name = name
    fake_cursor.fetchall.return_value = [
        ("uuid-1", "before text", 100, "Doc One", "https://example/1", "intro", 2),
        ("uuid-2", "target text", 100, "Doc One", "https://example/1", "intro", 3),
        ("uuid-3", "after text", 100, "Doc One", "https://example/1", "intro", 4),
    ]
    fake_conn = MagicMock()
    fake_conn.cursor.return_value.__enter__.return_value = fake_cursor
    fake_conn.cursor.return_value.__exit__.return_value = False

    fake_connect_ctx = MagicMock()
    fake_connect_ctx.__enter__.return_value = fake_conn
    fake_connect_ctx.__exit__.return_value = False

    with patch("psycopg.connect", return_value=fake_connect_ctx):
        output = adapter.refine(
            doc_title="Doc One",
            chunk_index=3,
            query="tell me more",
            window=1,
            request_id="req-refine",
        )

    results = output.results
    assert len(results) == 3
    assert results[0].text == "before text"
    assert results[0].chunk_index == 2
    assert results[1].text == "target text"
    assert results[1].chunk_index == 3
    assert results[2].text == "after text"
    assert results[2].chunk_index == 4
    assert all(r.request_id == "req-refine" for r in results)
    assert all(r.physical_index_id == index.id for r in results)
    assert all(r.score == 1.0 for r in results)
    assert not output.truncated

    executed_sql = fake_cursor.execute.call_args[0][0]
    assert "doc_title" in executed_sql
    assert "chunk_index BETWEEN" in executed_sql


def _make_fake_connection(col_names: list[str], rows: list[tuple]) -> MagicMock:
    """Build a psycopg connection context-manager mock returning the given rows."""
    fake_cursor = MagicMock()
    fake_cursor.description = [MagicMock(name=n) for n in col_names]
    for col, name in zip(fake_cursor.description, col_names, strict=True):
        col.name = name
    fake_cursor.fetchall.return_value = rows
    fake_cursor.fetchone.return_value = rows[0] if rows else None

    fake_conn = MagicMock()
    fake_conn.cursor.return_value.__enter__.return_value = fake_cursor
    fake_conn.cursor.return_value.__exit__.return_value = False

    fake_connect_ctx = MagicMock()
    fake_connect_ctx.__enter__.return_value = fake_conn
    fake_connect_ctx.__exit__.return_value = False
    return fake_connect_ctx


_REFINE_COLS = ["id", "chunk_text", "chunk_tokens", "doc_title", "doc_url", "doc_section", "chunk_index"]


def test_document_adapter_refine_section_strategy() -> None:
    """Section strategy: look up origin chunk's section, then fetch all section chunks."""
    source = _make_source()
    recipe = _make_recipe_version(
        {"embedding": {"model": "fake-model", "dimension": 768}}
    )
    index = _make_physical_index("idx_test_table")

    adapter = DocumentAdapter(
        source=source,
        physical_index=index,
        recipe_version=recipe,
        vectors_db_url="postgresql+psycopg://retrievalhub:pw@localhost:5433/rv",
    )

    # _get_chunk returns a single row with doc_section="Recommendations"
    get_chunk_conn = _make_fake_connection(
        _REFINE_COLS,
        [("uuid-origin", "origin text", 100, "VA CPG PTSD", "https://example/1", "Recommendations", 11)],
    )

    # _section_chunks returns 4 rows from that section
    section_conn = _make_fake_connection(
        _REFINE_COLS,
        [
            ("uuid-10", "chunk 10 text", 100, "VA CPG PTSD", "https://example/1", "Recommendations", 10),
            ("uuid-11", "chunk 11 text", 100, "VA CPG PTSD", "https://example/1", "Recommendations", 11),
            ("uuid-12", "chunk 12 text", 100, "VA CPG PTSD", "https://example/1", "Recommendations", 12),
            ("uuid-13", "chunk 13 text", 100, "VA CPG PTSD", "https://example/1", "Recommendations", 13),
        ],
    )

    with patch("psycopg.connect", side_effect=[get_chunk_conn, section_conn]):
        output = adapter.refine(
            doc_title="VA CPG PTSD",
            chunk_index=11,
            query="full section",
            window=2,
            request_id="req-sec",
            strategy="section",
        )

    assert len(output.results) == 4
    assert all(r.doc_section == "Recommendations" for r in output.results)
    assert [r.chunk_index for r in output.results] == [10, 11, 12, 13]
    assert not output.truncated


def test_document_adapter_refine_section_no_section_falls_back() -> None:
    """When origin chunk has doc_section=None, section strategy returns just that chunk."""
    source = _make_source()
    recipe = _make_recipe_version(
        {"embedding": {"model": "fake-model", "dimension": 768}}
    )
    index = _make_physical_index("idx_test_table")

    adapter = DocumentAdapter(
        source=source,
        physical_index=index,
        recipe_version=recipe,
        vectors_db_url="postgresql+psycopg://retrievalhub:pw@localhost:5433/rv",
    )

    # _get_chunk returns a row with doc_section=None
    get_chunk_conn = _make_fake_connection(
        _REFINE_COLS,
        [("uuid-5", "orphan text", 80, "Doc X", "https://example/x", None, 5)],
    )

    with patch("psycopg.connect", return_value=get_chunk_conn):
        output = adapter.refine(
            doc_title="Doc X",
            chunk_index=5,
            query="more context",
            window=2,
            request_id="req-nosec",
            strategy="section",
        )

    assert len(output.results) == 1
    assert output.results[0].chunk_index == 5
    assert output.results[0].doc_section is None
    assert not output.truncated


def test_document_adapter_refine_truncation() -> None:
    """Truncation keeps origin and expands outward until budget is exhausted."""
    source = _make_source()
    recipe = _make_recipe_version(
        {"embedding": {"model": "fake-model", "dimension": 768}}
    )
    index = _make_physical_index("idx_test_table")

    adapter = DocumentAdapter(
        source=source,
        physical_index=index,
        recipe_version=recipe,
        vectors_db_url="postgresql+psycopg://retrievalhub:pw@localhost:5433/rv",
    )

    # 5 chunks, each 100 tokens, origin at chunk_index=2 (position 2 in list)
    section_rows = [
        ("uuid-0", "chunk 0", 100, "Doc", "https://example/d", "S1", 0),
        ("uuid-1", "chunk 1", 100, "Doc", "https://example/d", "S1", 1),
        ("uuid-2", "chunk 2", 100, "Doc", "https://example/d", "S1", 2),
        ("uuid-3", "chunk 3", 100, "Doc", "https://example/d", "S1", 3),
        ("uuid-4", "chunk 4", 100, "Doc", "https://example/d", "S1", 4),
    ]

    get_chunk_conn = _make_fake_connection(
        _REFINE_COLS,
        [section_rows[2]],  # origin chunk
    )
    section_conn = _make_fake_connection(_REFINE_COLS, section_rows)

    # Budget=250: origin(100) + before-1(100)=200 <= 250; + after-1(100)=300 > 250 -> stop
    # Result: chunks at positions 1 and 2 (chunk_index 1 and 2)
    with patch("psycopg.connect", side_effect=[get_chunk_conn, section_conn]):
        output = adapter.refine(
            doc_title="Doc",
            chunk_index=2,
            query="more",
            window=2,
            request_id="req-trunc",
            strategy="section",
            max_context_tokens=250,
        )

    assert len(output.results) == 2
    assert [r.chunk_index for r in output.results] == [1, 2]
    assert output.truncated is True
    assert output.total_chunks == 5


def test_document_adapter_refine_truncation_fits_all() -> None:
    """When budget exceeds total tokens, all chunks are returned without truncation."""
    source = _make_source()
    recipe = _make_recipe_version(
        {"embedding": {"model": "fake-model", "dimension": 768}}
    )
    index = _make_physical_index("idx_test_table")

    adapter = DocumentAdapter(
        source=source,
        physical_index=index,
        recipe_version=recipe,
        vectors_db_url="postgresql+psycopg://retrievalhub:pw@localhost:5433/rv",
    )

    section_rows = [
        ("uuid-0", "chunk 0", 100, "Doc", "https://example/d", "S1", 0),
        ("uuid-1", "chunk 1", 100, "Doc", "https://example/d", "S1", 1),
        ("uuid-2", "chunk 2", 100, "Doc", "https://example/d", "S1", 2),
        ("uuid-3", "chunk 3", 100, "Doc", "https://example/d", "S1", 3),
        ("uuid-4", "chunk 4", 100, "Doc", "https://example/d", "S1", 4),
    ]

    get_chunk_conn = _make_fake_connection(_REFINE_COLS, [section_rows[2]])
    section_conn = _make_fake_connection(_REFINE_COLS, section_rows)

    with patch("psycopg.connect", side_effect=[get_chunk_conn, section_conn]):
        output = adapter.refine(
            doc_title="Doc",
            chunk_index=2,
            query="all of it",
            window=2,
            request_id="req-fit",
            strategy="section",
            max_context_tokens=600,
        )

    assert len(output.results) == 5
    assert output.truncated is False
    assert output.total_chunks is None


def test_document_adapter_embedding_model_name_missing_raises() -> None:
    source = _make_source()
    recipe = _make_recipe_version({"embedding": {}})  # no model key
    index = _make_physical_index("idx_test_table")

    adapter = DocumentAdapter(
        source=source,
        physical_index=index,
        recipe_version=recipe,
        vectors_db_url="postgresql+psycopg://ignored",
    )

    with pytest.raises(ValueError, match=r"embedding\.model"):
        adapter._embedding_model_name()
