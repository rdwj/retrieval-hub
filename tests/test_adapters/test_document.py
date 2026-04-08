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
    # Every result must carry the full lineage handle.
    assert first.physical_index_id == index.id
    assert first.recipe_version == recipe.version_number
    assert first.request_id == "req-abc"

    second = results[1]
    assert second.doc_section is None
    assert second.score == pytest.approx(0.87)


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
