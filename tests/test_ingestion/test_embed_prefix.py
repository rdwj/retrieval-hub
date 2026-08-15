"""Tests for configurable embedding prefixes.

Verifies that ChunkEmbedder and QueryEmbedder honor custom, empty, and
default prefix settings. Uses the same mock pattern as ``test_embed.py``.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import numpy as np

from retrieval_hub.ingestion.chunking.token_fixed import Chunk


def _make_chunk(text: str, index: int = 0) -> Chunk:
    return Chunk(
        text=text,
        token_count=len(text.split()),
        chunk_index=index,
        doc_url="https://example.com/doc",
        doc_title="Example",
        doc_section=None,
    )


def _capturing_model(dimension: int = 768) -> tuple[MagicMock, list[list[str]]]:
    """Return a fake model and a list that captures every ``encode`` call."""
    model = MagicMock()
    model.get_sentence_embedding_dimension.return_value = dimension
    captured: list[list[str]] = []

    def encode(texts, **kwargs):  # type: ignore[no-untyped-def]
        captured.append(list(texts))
        return np.zeros((len(texts), dimension), dtype=float)

    model.encode.side_effect = encode
    return model, captured


# -- ChunkEmbedder prefix tests ------------------------------------------


def test_chunk_embedder_default_prefix() -> None:
    """Default prefix should be ``search_document: `` for backward compat."""
    from retrieval_hub.ingestion import embed

    model, captured = _capturing_model()

    with patch.object(embed, "_load_model", return_value=model):
        embedder = embed.ChunkEmbedder(cache_dir=None)
        embedder.embed_chunks([_make_chunk("hello")])

    assert captured[0] == ["search_document: hello"]


def test_chunk_embedder_empty_prefix() -> None:
    """An empty prefix should pass raw text through without any prefix."""
    from retrieval_hub.ingestion import embed

    model, captured = _capturing_model()

    with patch.object(embed, "_load_model", return_value=model):
        embedder = embed.ChunkEmbedder(cache_dir=None, document_prefix="")
        embedder.embed_chunks([_make_chunk("raw text")])

    assert captured[0] == ["raw text"]


def test_chunk_embedder_custom_prefix() -> None:
    """A custom prefix should be prepended instead of the default."""
    from retrieval_hub.ingestion import embed

    model, captured = _capturing_model()

    with patch.object(embed, "_load_model", return_value=model):
        embedder = embed.ChunkEmbedder(cache_dir=None, document_prefix="passage: ")
        embedder.embed_chunks([_make_chunk("some text")])

    assert captured[0] == ["passage: some text"]


# -- QueryEmbedder prefix tests ------------------------------------------


def test_query_embedder_default_prefix() -> None:
    """Default prefix should be ``search_query: `` for backward compat."""
    from retrieval_hub.ingestion import embed

    model, captured = _capturing_model()

    with patch.object(embed, "_load_model", return_value=model):
        embedder = embed.QueryEmbedder(cache_dir=None)
        embedder.embed("what is hypertension")

    assert captured[0] == ["search_query: what is hypertension"]


def test_query_embedder_empty_prefix() -> None:
    """An empty prefix should pass the raw query text."""
    from retrieval_hub.ingestion import embed

    model, captured = _capturing_model()

    with patch.object(embed, "_load_model", return_value=model):
        embedder = embed.QueryEmbedder(cache_dir=None, query_prefix="")
        embedder.embed("raw query")

    assert captured[0] == ["raw query"]
