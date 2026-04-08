"""Tests for the embed stage.

sentence-transformers is a heavy dependency, so we mock ``_load_model`` to
return a fake model that produces deterministic vectors. This lets the test
suite stay fast (<1s) and not require a model download.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

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


def _fake_model(dimension: int = 768) -> MagicMock:
    model = MagicMock()
    model.get_sentence_embedding_dimension.return_value = dimension

    def encode(texts, **kwargs):  # type: ignore[no-untyped-def]
        # Return one deterministic vector per input text.
        import numpy as np

        vectors = []
        for i, _ in enumerate(texts):
            vec = np.zeros(dimension, dtype=float)
            vec[i % dimension] = 1.0
            vectors.append(vec)
        return np.array(vectors)

    model.encode.side_effect = encode
    return model


def test_chunk_embedder_returns_one_vector_per_chunk() -> None:
    from retrieval_hub.ingestion import embed

    chunks = [_make_chunk("first chunk text", 0), _make_chunk("second chunk text", 1)]

    with patch.object(embed, "_load_model", return_value=_fake_model(768)):
        embedder = embed.ChunkEmbedder(cache_dir=None)
        vectors = embedder.embed_chunks(chunks)

    assert len(vectors) == 2
    assert all(len(v) == 768 for v in vectors)


def test_chunk_embedder_empty_input_returns_empty() -> None:
    from retrieval_hub.ingestion import embed

    with patch.object(embed, "_load_model", return_value=_fake_model(768)):
        embedder = embed.ChunkEmbedder(cache_dir=None)
        vectors = embedder.embed_chunks([])

    assert vectors == []


def test_chunk_embedder_reports_dimension() -> None:
    from retrieval_hub.ingestion import embed

    with patch.object(embed, "_load_model", return_value=_fake_model(384)):
        embedder = embed.ChunkEmbedder(cache_dir=None)
        assert embedder.dimension == 384


def test_chunk_embedder_dimension_raises_when_model_returns_none() -> None:
    from retrieval_hub.ingestion import embed

    broken_model = MagicMock()
    broken_model.get_sentence_embedding_dimension.return_value = None
    with patch.object(embed, "_load_model", return_value=broken_model):
        embedder = embed.ChunkEmbedder(cache_dir=None)
        with pytest.raises(RuntimeError, match="reported no dimension"):
            _ = embedder.dimension


def test_query_embedder_returns_single_vector() -> None:
    from retrieval_hub.ingestion import embed

    with patch.object(embed, "_load_model", return_value=_fake_model(768)):
        q_embedder = embed.QueryEmbedder(cache_dir=None)
        vec = q_embedder.embed("what is Llama Stack")

    assert len(vec) == 768
    assert all(isinstance(v, float) for v in vec)


def test_chunk_embedder_uses_nomic_prefix() -> None:
    """Verify chunks are prefixed with ``search_document: `` before encoding."""
    from retrieval_hub.ingestion import embed

    captured_texts: list[list[str]] = []

    fake = _fake_model(768)

    def encode(texts, **kwargs):  # type: ignore[no-untyped-def]
        captured_texts.append(list(texts))
        import numpy as np

        return np.zeros((len(texts), 768), dtype=float)

    fake.encode.side_effect = encode

    with patch.object(embed, "_load_model", return_value=fake):
        embedder = embed.ChunkEmbedder(cache_dir=None)
        embedder.embed_chunks([_make_chunk("hello world", 0)])

    assert captured_texts, "encode was not called"
    assert captured_texts[0][0].startswith("search_document: ")
