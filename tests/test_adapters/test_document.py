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


def test_document_adapter_rejects_scope_entity_id() -> None:
    """DocumentAdapter raises ValueError when scope_entity_id is provided."""
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

    with pytest.raises(ValueError, match="scope_entity_id is only supported for graph-family"):
        adapter.retrieve(
            "test query",
            top_k=5,
            request_id="req-1",
            scope_entity_id="some-entity-id",
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
    assert first.chunk_id == "chunk-uuid-1"
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
    assert second.chunk_id == "chunk-uuid-2"
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
    assert results[0].chunk_id == "uuid-1"
    assert results[0].text == "before text"
    assert results[0].chunk_index == 2
    assert results[1].chunk_id == "uuid-2"
    assert results[1].text == "target text"
    assert results[1].chunk_index == 3
    assert results[2].chunk_id == "uuid-3"
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


def test_document_adapter_uses_explicit_embedding_endpoint() -> None:
    """When embedding_endpoint is passed, _embedding_endpoint() returns it."""
    source = _make_source()
    recipe = _make_recipe_version(
        {"embedding": {"model": "m", "dimension": 768, "endpoint": "http://recipe:9000"}}
    )
    index = _make_physical_index("test_table")
    adapter = DocumentAdapter(
        source=source,
        physical_index=index,
        recipe_version=recipe,
        vectors_db_url="postgresql://fake",
        embedding_endpoint="http://registry:8000",
    )
    assert adapter._embedding_endpoint() == "http://registry:8000"


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


# ---------------------------------------------------------------------------
# Cross-reference refinement tests
# ---------------------------------------------------------------------------

_XREF_COLS = [
    "id", "chunk_text", "chunk_tokens", "doc_title",
    "doc_url", "doc_section", "chunk_index", "score",
]


def _semantic_context_ptsd_sud() -> dict:
    """Minimal semantic context with a PTSD <-> SUD bidirectional relationship."""
    return {
        "entities": [
            {
                "name": "PTSD",
                "entity_type": "condition",
                "definition": "Post-traumatic stress disorder",
                "doc_titles": ["PTSD Doc"],
            },
            {
                "name": "SUD",
                "entity_type": "condition",
                "definition": "Substance use disorder",
                "doc_titles": ["SUD Doc"],
            },
        ],
        "relationships": [
            {
                "source_entity": "PTSD",
                "target_entity": "SUD",
                "relationship_type": "comorbidity",
                "directionality": "bidirectional",
            },
        ],
    }


def test_refine_cross_reference_happy_path() -> None:
    """Origin chunk from PTSD Doc, cross-reference hits from SUD Doc."""
    source = _make_source()
    source.semantic_context = _semantic_context_ptsd_sud()
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

    # Mock the embedder
    fake_embedder = MagicMock()
    fake_embedder.embed.return_value = [0.1] * 768

    # Connection 1: _get_chunk returns the origin chunk
    get_chunk_conn = _make_fake_connection(
        _REFINE_COLS,
        [("uuid-origin", "ptsd origin text", 100, "PTSD Doc", "https://example/ptsd", "Treatment", 10)],
    )

    # Connection 2: _filtered_similarity_search returns 2 xref rows
    xref_cursor = MagicMock()
    xref_cursor.description = [MagicMock(name=n) for n in _XREF_COLS]
    for col, name in zip(xref_cursor.description, _XREF_COLS, strict=True):
        col.name = name
    xref_cursor.fetchall.return_value = [
        ("uuid-xref-1", "sud comorbidity text", 120, "SUD Doc", "https://example/sud", "Screening", 5, 0.88),
        ("uuid-xref-2", "sud treatment text", 110, "SUD Doc", "https://example/sud", "Treatment", 8, 0.82),
    ]
    xref_conn_inner = MagicMock()
    xref_conn_inner.cursor.return_value.__enter__.return_value = xref_cursor
    xref_conn_inner.cursor.return_value.__exit__.return_value = False
    xref_connect_ctx = MagicMock()
    xref_connect_ctx.__enter__.return_value = xref_conn_inner
    xref_connect_ctx.__exit__.return_value = False

    with (
        patch(
            "retrieval_hub.ingestion.embed.QueryEmbedder",
            return_value=fake_embedder,
        ),
        patch("psycopg.connect", side_effect=[get_chunk_conn, xref_connect_ctx]),
        patch("pgvector.psycopg.register_vector"),
    ):
        output = adapter.refine(
            doc_title="PTSD Doc",
            chunk_index=10,
            query="substance use comorbidity",
            window=5,
            request_id="req-xref",
            strategy="cross_reference",
        )

    assert len(output.results) == 3
    # Origin chunk
    assert output.results[0].doc_title == "PTSD Doc"
    assert output.results[0].score == 1.0
    assert output.results[0].chunk_index == 10
    # Cross-reference hits
    assert output.results[1].doc_title == "SUD Doc"
    assert output.results[1].score == pytest.approx(0.88)
    assert output.results[2].doc_title == "SUD Doc"
    assert output.results[2].score == pytest.approx(0.82)
    # Lineage on all results
    for r in output.results:
        assert r.physical_index_id == index.id
        assert r.recipe_version == recipe.version_number
        assert r.request_id == "req-xref"
    assert output.truncated is False


def test_cross_reference_no_semantic_context() -> None:
    """Source with no semantic_context returns only the origin chunk."""
    source = _make_source()
    source.semantic_context = None
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

    get_chunk_conn = _make_fake_connection(
        _REFINE_COLS,
        [("uuid-1", "some text", 100, "Lone Doc", "https://example/lone", "Intro", 3)],
    )

    with patch("psycopg.connect", return_value=get_chunk_conn):
        output = adapter.refine(
            doc_title="Lone Doc",
            chunk_index=3,
            query="anything",
            window=5,
            request_id="req-nosc",
            strategy="cross_reference",
        )

    assert len(output.results) == 1
    assert output.results[0].doc_title == "Lone Doc"
    assert output.results[0].score == 1.0
    assert output.truncated is False


def test_cross_reference_entity_not_found() -> None:
    """Origin doc_title matches no entity -- returns only the origin chunk."""
    source = _make_source()
    source.semantic_context = {
        "entities": [
            {"name": "COPD", "entity_type": "condition", "definition": "...", "doc_titles": ["COPD Doc"]},
        ],
        "relationships": [],
    }
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

    get_chunk_conn = _make_fake_connection(
        _REFINE_COLS,
        [("uuid-unk", "unknown text", 100, "Unknown Doc", "https://example/unk", None, 7)],
    )

    with patch("psycopg.connect", return_value=get_chunk_conn):
        output = adapter.refine(
            doc_title="Unknown Doc",
            chunk_index=7,
            query="anything",
            window=5,
            request_id="req-notfound",
            strategy="cross_reference",
        )

    assert len(output.results) == 1
    assert output.results[0].doc_title == "Unknown Doc"
    assert output.truncated is False


def test_cross_reference_no_relationships() -> None:
    """Origin entity exists but has no relationships -- returns only origin."""
    source = _make_source()
    source.semantic_context = {
        "entities": [
            {"name": "COPD", "entity_type": "condition", "definition": "...", "doc_titles": ["COPD Doc"]},
        ],
        "relationships": [],
    }
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

    get_chunk_conn = _make_fake_connection(
        _REFINE_COLS,
        [("uuid-copd", "copd text", 100, "COPD Doc", "https://example/copd", "Intro", 0)],
    )

    with patch("psycopg.connect", return_value=get_chunk_conn):
        output = adapter.refine(
            doc_title="COPD Doc",
            chunk_index=0,
            query="anything",
            window=5,
            request_id="req-norel",
            strategy="cross_reference",
        )

    assert len(output.results) == 1
    assert output.results[0].doc_title == "COPD Doc"
    assert output.truncated is False


def test_cross_reference_directionality_respected() -> None:
    """Directed relationship PHQ-9 -> MDD should not produce xrefs when origin is MDD."""
    source = _make_source()
    source.semantic_context = {
        "entities": [
            {"name": "MDD", "entity_type": "condition", "definition": "Major depressive disorder", "doc_titles": ["MDD Doc"]},
            {"name": "PHQ-9", "entity_type": "instrument", "definition": "Screening instrument", "doc_titles": []},
        ],
        "relationships": [
            {
                "source_entity": "PHQ-9",
                "target_entity": "MDD",
                "relationship_type": "screens_for",
                "directionality": "directed",
            },
        ],
    }
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

    get_chunk_conn = _make_fake_connection(
        _REFINE_COLS,
        [("uuid-mdd", "mdd text", 100, "MDD Doc", "https://example/mdd", "Diagnosis", 2)],
    )

    with patch("psycopg.connect", return_value=get_chunk_conn):
        output = adapter.refine(
            doc_title="MDD Doc",
            chunk_index=2,
            query="depression screening",
            window=5,
            request_id="req-dir",
            strategy="cross_reference",
        )

    assert len(output.results) == 1
    assert output.results[0].doc_title == "MDD Doc"
    assert output.truncated is False


def test_cross_reference_truncation() -> None:
    """Cross-reference results exceeding max_context_tokens are truncated."""
    source = _make_source()
    source.semantic_context = _semantic_context_ptsd_sud()
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

    fake_embedder = MagicMock()
    fake_embedder.embed.return_value = [0.1] * 768

    # Origin chunk: 200 tokens
    get_chunk_conn = _make_fake_connection(
        _REFINE_COLS,
        [("uuid-origin", "ptsd text", 200, "PTSD Doc", "https://example/ptsd", "S1", 10)],
    )

    # 3 xref rows, each 200 tokens
    xref_cursor = MagicMock()
    xref_cursor.description = [MagicMock(name=n) for n in _XREF_COLS]
    for col, name in zip(xref_cursor.description, _XREF_COLS, strict=True):
        col.name = name
    xref_cursor.fetchall.return_value = [
        ("uuid-x1", "xref 1", 200, "SUD Doc", "https://example/sud", "S1", 1, 0.90),
        ("uuid-x2", "xref 2", 200, "SUD Doc", "https://example/sud", "S2", 4, 0.85),
        ("uuid-x3", "xref 3", 200, "SUD Doc", "https://example/sud", "S3", 7, 0.80),
    ]
    xref_conn_inner = MagicMock()
    xref_conn_inner.cursor.return_value.__enter__.return_value = xref_cursor
    xref_conn_inner.cursor.return_value.__exit__.return_value = False
    xref_connect_ctx = MagicMock()
    xref_connect_ctx.__enter__.return_value = xref_conn_inner
    xref_connect_ctx.__exit__.return_value = False

    with (
        patch(
            "retrieval_hub.ingestion.embed.QueryEmbedder",
            return_value=fake_embedder,
        ),
        patch("psycopg.connect", side_effect=[get_chunk_conn, xref_connect_ctx]),
        patch("pgvector.psycopg.register_vector"),
    ):
        output = adapter.refine(
            doc_title="PTSD Doc",
            chunk_index=10,
            query="substance use comorbidity",
            window=5,
            request_id="req-trunc-xref",
            strategy="cross_reference",
            max_context_tokens=500,
        )

    # origin(200) + 1 xref(200) = 400 fits; + another(200) = 600 > 500
    assert len(output.results) == 2
    assert output.results[0].doc_title == "PTSD Doc"
    assert output.results[1].doc_title == "SUD Doc"
    assert output.truncated is True
    assert output.total_chunks == 4  # 1 origin + 3 xref before truncation


def test_resolve_cross_reference_targets() -> None:
    """Unit test for _resolve_cross_reference_targets -- pure logic, no mocking."""
    source = _make_source()
    source.semantic_context = {
        "entities": [
            {"name": "PTSD", "entity_type": "condition", "definition": "...", "doc_titles": ["PTSD Doc"]},
            {"name": "SUD", "entity_type": "condition", "definition": "...", "doc_titles": ["SUD Doc"]},
            {"name": "MDD", "entity_type": "condition", "definition": "...", "doc_titles": ["MDD Doc"]},
            {"name": "PHQ-9", "entity_type": "instrument", "definition": "...", "doc_titles": []},
        ],
        "relationships": [
            {"source_entity": "PTSD", "target_entity": "SUD", "relationship_type": "comorbidity", "directionality": "bidirectional"},
            {"source_entity": "PTSD", "target_entity": "MDD", "relationship_type": "comorbidity", "directionality": "bidirectional"},
            {"source_entity": "PHQ-9", "target_entity": "MDD", "relationship_type": "screens_for", "directionality": "directed"},
        ],
    }
    recipe = _make_recipe_version(
        {"embedding": {"model": "fake-model", "dimension": 768}}
    )
    index = _make_physical_index("idx_test_table")

    adapter = DocumentAdapter(
        source=source,
        physical_index=index,
        recipe_version=recipe,
        vectors_db_url="postgresql+psycopg://ignored",
    )

    # PTSD -> bidirectional with SUD and MDD
    assert adapter._resolve_cross_reference_targets("PTSD Doc") == ["SUD Doc", "MDD Doc"]

    # SUD -> bidirectional with PTSD only
    assert adapter._resolve_cross_reference_targets("SUD Doc") == ["PTSD Doc"]

    # MDD -> bidirectional with PTSD, but NOT PHQ-9 (directed, MDD is the target)
    assert adapter._resolve_cross_reference_targets("MDD Doc") == ["PTSD Doc"]

    # Unknown doc matches no entity
    assert adapter._resolve_cross_reference_targets("Unknown Doc") == []


# ---------------------------------------------------------------------------
# Entity-arc refinement tests
# ---------------------------------------------------------------------------


def _extract_cursor(fake_connect_ctx: MagicMock) -> MagicMock:
    """Reach into a _make_fake_connection mock and return the inner cursor."""
    return fake_connect_ctx.__enter__.return_value.cursor.return_value.__enter__.return_value


def test_keyword_search_with_scores() -> None:
    """_keyword_search_with_scores builds OR'd ILIKE SQL and returns scored rows."""
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

    kw_conn = _make_fake_connection(
        _XREF_COLS,
        [
            ("uuid-1", "SSRI mention here", 100, "PTSD Doc", "https://example/ptsd", "Treatment", 17, 0.45),
            ("uuid-2", "selective serotonin text", 120, "PTSD Doc", "https://example/ptsd", "Evidence", 46, 0.38),
        ],
    )

    with (
        patch("psycopg.connect", return_value=kw_conn),
        patch("pgvector.psycopg.register_vector") as mock_register,
    ):
        rows = adapter._keyword_search_with_scores(
            ["SSRIs", "selective serotonin"],
            "PTSD Doc",
            [0.1] * 768,
        )

    assert len(rows) == 2
    assert rows[0]["chunk_text"] == "SSRI mention here"
    assert rows[0]["score"] == pytest.approx(0.45)
    assert rows[1]["chunk_index"] == 46

    # Verify SQL has ILIKE for both patterns
    fake_cursor = _extract_cursor(kw_conn)
    executed_sql = fake_cursor.execute.call_args[0][0]
    assert "ILIKE" in executed_sql
    assert executed_sql.count("ILIKE") == 2  # One per pattern

    mock_register.assert_called_once()


def test_resolve_entity_aliases_found() -> None:
    """_resolve_entity_aliases returns aliases for a matching entity name (case-insensitive)."""
    source = _make_source()
    source.semantic_context = {
        "entities": [
            {
                "name": "SSRIs",
                "entity_type": "drug_class",
                "definition": "Selective serotonin reuptake inhibitors",
                "aliases": ["selective serotonin reuptake inhibitors", "SSRI"],
            },
        ],
        "relationships": [],
    }
    recipe = _make_recipe_version(
        {"embedding": {"model": "fake-model", "dimension": 768}}
    )
    index = _make_physical_index("idx_test_table")
    adapter = DocumentAdapter(
        source=source,
        physical_index=index,
        recipe_version=recipe,
        vectors_db_url="postgresql+psycopg://ignored",
    )

    # Exact match
    assert adapter._resolve_entity_aliases("SSRIs") == [
        "selective serotonin reuptake inhibitors",
        "SSRI",
    ]

    # Case-insensitive match
    assert adapter._resolve_entity_aliases("ssris") == [
        "selective serotonin reuptake inhibitors",
        "SSRI",
    ]

    # No match
    assert adapter._resolve_entity_aliases("unknown-entity") == []


def test_resolve_entity_aliases_no_semantic_context() -> None:
    """_resolve_entity_aliases returns empty when semantic_context is None."""
    source = _make_source()
    source.semantic_context = None
    recipe = _make_recipe_version(
        {"embedding": {"model": "fake-model", "dimension": 768}}
    )
    index = _make_physical_index("idx_test_table")
    adapter = DocumentAdapter(
        source=source,
        physical_index=index,
        recipe_version=recipe,
        vectors_db_url="postgresql+psycopg://ignored",
    )

    assert adapter._resolve_entity_aliases("anything") == []


def test_entity_arc_refine_happy_path() -> None:
    """Vector and keyword results are unioned, deduped by chunk_index, and sorted structurally."""
    source = _make_source()
    source.semantic_context = {
        "entities": [
            {"name": "SSRIs", "entity_type": "drug_class", "definition": "...", "aliases": []},
        ],
        "relationships": [],
    }
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

    fake_embedder = MagicMock()
    fake_embedder.embed.return_value = [0.1] * 768

    # _filtered_similarity_search: 3 vector results
    vector_conn = _make_fake_connection(_XREF_COLS, [
        ("uuid-v1", "vector hit 1", 100, "PTSD Doc", "https://ex/ptsd", "Treatment", 17, 0.55),
        ("uuid-v2", "vector hit 2", 100, "PTSD Doc", "https://ex/ptsd", "Evidence", 33, 0.48),
        ("uuid-v3", "vector hit 3", 100, "PTSD Doc", "https://ex/ptsd", "Appendix", 96, 0.42),
    ])

    # _keyword_search_with_scores: 2 keyword results
    # chunk 33 overlaps with vector (keyword score 0.50 > vector 0.48)
    # chunk 75 is keyword-only
    keyword_conn = _make_fake_connection(_XREF_COLS, [
        ("uuid-k1", "vector hit 2", 100, "PTSD Doc", "https://ex/ptsd", "Evidence", 33, 0.50),
        ("uuid-k2", "keyword only hit", 100, "PTSD Doc", "https://ex/ptsd", "Discussion", 75, 0.35),
    ])

    with (
        patch("retrieval_hub.ingestion.embed.QueryEmbedder", return_value=fake_embedder),
        patch("psycopg.connect", side_effect=[vector_conn, keyword_conn]),
        patch("pgvector.psycopg.register_vector"),
    ):
        output = adapter.refine(
            doc_title="PTSD Doc",
            chunk_index=0,
            query="SSRIs",
            window=5,
            request_id="req-arc",
            strategy="entity_arc",
        )

    # 4 unique chunks (17, 33, 75, 96), all above 0.30 default floor
    assert len(output.results) == 4
    # Ordered by chunk_index (structural ordering)
    assert [r.chunk_index for r in output.results] == [17, 33, 75, 96]
    # Chunk 33: keyword score (0.50) beats vector score (0.48)
    chunk_33 = [r for r in output.results if r.chunk_index == 33][0]
    assert chunk_33.score == pytest.approx(0.50)
    # Chunk 17 keeps its vector score
    assert output.results[0].score == pytest.approx(0.55)
    assert not output.truncated


def test_entity_arc_refine_with_aliases() -> None:
    """When the entity has aliases, keyword search uses all patterns."""
    source = _make_source()
    source.semantic_context = {
        "entities": [
            {
                "name": "SSRIs",
                "entity_type": "drug_class",
                "definition": "...",
                "aliases": ["selective serotonin reuptake inhibitors"],
            },
        ],
        "relationships": [],
    }
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

    fake_embedder = MagicMock()
    fake_embedder.embed.return_value = [0.1] * 768

    vector_conn = _make_fake_connection(_XREF_COLS, [
        ("uuid-v1", "some chunk", 100, "Doc", "https://ex/d", "S1", 5, 0.60),
    ])
    keyword_conn = _make_fake_connection(_XREF_COLS, [
        ("uuid-k1", "selective serotonin match", 100, "Doc", "https://ex/d", "S2", 12, 0.40),
    ])

    with (
        patch("retrieval_hub.ingestion.embed.QueryEmbedder", return_value=fake_embedder),
        patch("psycopg.connect", side_effect=[vector_conn, keyword_conn]),
        patch("pgvector.psycopg.register_vector"),
    ):
        output = adapter.refine(
            doc_title="Doc",
            chunk_index=0,
            query="SSRIs",
            window=5,
            request_id="req-alias",
            strategy="entity_arc",
        )

    assert len(output.results) == 2
    # Verify the keyword SQL had 2 ILIKE clauses (entity + alias)
    kw_cursor = _extract_cursor(keyword_conn)
    executed_sql = kw_cursor.execute.call_args[0][0]
    assert executed_sql.count("ILIKE") == 2


def test_entity_arc_refine_score_floor() -> None:
    """Keyword-only matches below the score floor are filtered out."""
    source = _make_source()
    source.semantic_context = {
        "entities": [
            {"name": "SSRIs", "entity_type": "drug_class", "definition": "...", "aliases": []},
        ],
        "relationships": [],
    }
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

    fake_embedder = MagicMock()
    fake_embedder.embed.return_value = [0.1] * 768

    vector_conn = _make_fake_connection(_XREF_COLS, [
        ("uuid-v1", "above floor", 100, "Doc", "https://ex/d", "S1", 5, 0.50),
    ])
    keyword_conn = _make_fake_connection(_XREF_COLS, [
        ("uuid-k1", "below floor", 100, "Doc", "https://ex/d", "S2", 20, 0.10),
    ])

    with (
        patch("retrieval_hub.ingestion.embed.QueryEmbedder", return_value=fake_embedder),
        patch("psycopg.connect", side_effect=[vector_conn, keyword_conn]),
        patch("pgvector.psycopg.register_vector"),
    ):
        output = adapter.refine(
            doc_title="Doc",
            chunk_index=0,
            query="SSRIs",
            window=5,
            request_id="req-floor",
            strategy="entity_arc",
        )

    # Only chunk 5 (score 0.50) survives; chunk 20 (score 0.10) is below 0.30 default floor
    assert len(output.results) == 1
    assert output.results[0].chunk_index == 5


def test_entity_arc_refine_custom_min_score() -> None:
    """A custom min_score overrides the default 0.30 floor."""
    source = _make_source()
    source.semantic_context = {
        "entities": [
            {"name": "SSRIs", "entity_type": "drug_class", "definition": "...", "aliases": []},
        ],
        "relationships": [],
    }
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

    fake_embedder = MagicMock()
    fake_embedder.embed.return_value = [0.1] * 768

    vector_conn = _make_fake_connection(_XREF_COLS, [
        ("uuid-v1", "high score", 100, "Doc", "https://ex/d", "S1", 5, 0.60),
        ("uuid-v2", "medium score", 100, "Doc", "https://ex/d", "S2", 10, 0.45),
    ])
    keyword_conn = _make_fake_connection(_XREF_COLS, [])

    with (
        patch("retrieval_hub.ingestion.embed.QueryEmbedder", return_value=fake_embedder),
        patch("psycopg.connect", side_effect=[vector_conn, keyword_conn]),
        patch("pgvector.psycopg.register_vector"),
    ):
        # min_score=0.50 should filter out the 0.45 chunk
        output = adapter.refine(
            doc_title="Doc",
            chunk_index=0,
            query="SSRIs",
            window=5,
            request_id="req-custom-floor",
            strategy="entity_arc",
            min_score=0.50,
        )

    assert len(output.results) == 1
    assert output.results[0].chunk_index == 5
    assert output.results[0].score == pytest.approx(0.60)


def test_entity_arc_refine_truncation() -> None:
    """Token budgeting selects top-scoring chunks and re-sorts by position."""
    source = _make_source()
    source.semantic_context = {
        "entities": [
            {"name": "SSRIs", "entity_type": "drug_class", "definition": "...", "aliases": []},
        ],
        "relationships": [],
    }
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

    fake_embedder = MagicMock()
    fake_embedder.embed.return_value = [0.1] * 768

    # 4 chunks, each 100 tokens, with varying scores
    vector_conn = _make_fake_connection(_XREF_COLS, [
        ("uuid-1", "chunk at 5", 100, "Doc", "https://ex/d", "S1", 5, 0.90),
        ("uuid-2", "chunk at 15", 100, "Doc", "https://ex/d", "S2", 15, 0.80),
        ("uuid-3", "chunk at 25", 100, "Doc", "https://ex/d", "S3", 25, 0.70),
        ("uuid-4", "chunk at 35", 100, "Doc", "https://ex/d", "S4", 35, 0.60),
    ])
    keyword_conn = _make_fake_connection(_XREF_COLS, [])

    with (
        patch("retrieval_hub.ingestion.embed.QueryEmbedder", return_value=fake_embedder),
        patch("psycopg.connect", side_effect=[vector_conn, keyword_conn]),
        patch("pgvector.psycopg.register_vector"),
    ):
        # Budget=250 fits 2 chunks (200 tokens), not all 4 (400 tokens)
        output = adapter.refine(
            doc_title="Doc",
            chunk_index=0,
            query="SSRIs",
            window=5,
            request_id="req-trunc-arc",
            strategy="entity_arc",
            max_context_tokens=250,
        )

    # Top 2 by score: chunk 5 (0.90) and chunk 15 (0.80), re-sorted by position
    assert len(output.results) == 2
    assert [r.chunk_index for r in output.results] == [5, 15]
    assert output.truncated is True
    assert output.total_chunks == 4


def test_entity_arc_refine_no_results() -> None:
    """Both vector and keyword searches returning empty produces empty RefineOutput."""
    source = _make_source()
    source.semantic_context = {
        "entities": [
            {"name": "SSRIs", "entity_type": "drug_class", "definition": "...", "aliases": []},
        ],
        "relationships": [],
    }
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

    fake_embedder = MagicMock()
    fake_embedder.embed.return_value = [0.1] * 768

    vector_conn = _make_fake_connection(_XREF_COLS, [])
    keyword_conn = _make_fake_connection(_XREF_COLS, [])

    with (
        patch("retrieval_hub.ingestion.embed.QueryEmbedder", return_value=fake_embedder),
        patch("psycopg.connect", side_effect=[vector_conn, keyword_conn]),
        patch("pgvector.psycopg.register_vector"),
    ):
        output = adapter.refine(
            doc_title="Doc",
            chunk_index=0,
            query="SSRIs",
            window=5,
            request_id="req-empty",
            strategy="entity_arc",
        )

    assert len(output.results) == 0
    assert not output.truncated


# ---------------------------------------------------------------------------
# doc_section filter tests
# ---------------------------------------------------------------------------

_RETRIEVE_COLS = ["id", "chunk_text", "doc_title", "doc_url", "doc_section", "chunk_index", "score"]


def test_similarity_search_with_doc_section_filter() -> None:
    """When doc_section is provided, _similarity_search adds a WHERE clause."""
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

    fake_conn_ctx = _make_fake_connection(
        _RETRIEVE_COLS,
        [
            ("uuid-1", "patient chunk", "Doc", "https://ex/d", "Patient", 0, 0.91),
        ],
    )

    with (
        patch("psycopg.connect", return_value=fake_conn_ctx),
        patch("pgvector.psycopg.register_vector"),
    ):
        rows = adapter._similarity_search(
            [0.1] * 768, top_k=5, doc_section=["Patient", "Condition"]
        )

    assert len(rows) == 1
    assert rows[0]["doc_section"] == "Patient"

    # Verify the executed SQL contains the WHERE clause with ANY
    fake_cursor = _extract_cursor(fake_conn_ctx)
    executed_sql = fake_cursor.execute.call_args[0][0]
    assert "WHERE doc_section = ANY(%s)" in executed_sql

    # Verify the doc_section list was passed as a parameter
    executed_params = fake_cursor.execute.call_args[0][1]
    assert ["Patient", "Condition"] in list(executed_params)


def test_similarity_search_without_doc_section_filter() -> None:
    """When doc_section is None, _similarity_search uses the unfiltered query."""
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

    fake_conn_ctx = _make_fake_connection(
        _RETRIEVE_COLS,
        [
            ("uuid-1", "any chunk", "Doc", "https://ex/d", "Intro", 0, 0.88),
        ],
    )

    with (
        patch("psycopg.connect", return_value=fake_conn_ctx),
        patch("pgvector.psycopg.register_vector"),
    ):
        rows = adapter._similarity_search([0.1] * 768, top_k=5, doc_section=None)

    assert len(rows) == 1

    fake_cursor = _extract_cursor(fake_conn_ctx)
    executed_sql = fake_cursor.execute.call_args[0][0]
    assert "WHERE" not in executed_sql


def test_retrieve_passes_doc_section_through() -> None:
    """The retrieve() method passes doc_section through to _similarity_search."""
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

    fake_embedder = MagicMock()
    fake_embedder.embed.return_value = [0.1] * 768

    fake_conn_ctx = _make_fake_connection(
        _RETRIEVE_COLS,
        [
            ("uuid-1", "condition chunk", "Doc", "https://ex/d", "Condition", 2, 0.85),
        ],
    )

    with (
        patch(
            "retrieval_hub.ingestion.embed.QueryEmbedder",
            return_value=fake_embedder,
        ),
        patch("psycopg.connect", return_value=fake_conn_ctx),
        patch("pgvector.psycopg.register_vector"),
    ):
        results = adapter.retrieve(
            "test query",
            top_k=5,
            request_id="req-ds",
            doc_section=["Condition"],
        )

    assert len(results) == 1
    assert results[0].doc_section == "Condition"

    # Verify the WHERE clause was applied
    fake_cursor = _extract_cursor(fake_conn_ctx)
    executed_sql = fake_cursor.execute.call_args[0][0]
    assert "WHERE doc_section = ANY(%s)" in executed_sql


def test_retrieve_without_doc_section_is_backward_compatible() -> None:
    """Calling retrieve() without doc_section produces the unfiltered query."""
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

    fake_embedder = MagicMock()
    fake_embedder.embed.return_value = [0.1] * 768

    fake_conn_ctx = _make_fake_connection(
        _RETRIEVE_COLS,
        [
            ("uuid-1", "any chunk", "Doc", "https://ex/d", "Intro", 0, 0.90),
        ],
    )

    with (
        patch(
            "retrieval_hub.ingestion.embed.QueryEmbedder",
            return_value=fake_embedder,
        ),
        patch("psycopg.connect", return_value=fake_conn_ctx),
        patch("pgvector.psycopg.register_vector"),
    ):
        # Call without doc_section -- backward compatible
        results = adapter.retrieve("test query", top_k=5, request_id="req-compat")

    assert len(results) == 1

    fake_cursor = _extract_cursor(fake_conn_ctx)
    executed_sql = fake_cursor.execute.call_args[0][0]
    assert "WHERE" not in executed_sql
