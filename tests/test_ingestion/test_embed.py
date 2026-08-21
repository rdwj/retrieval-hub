"""Tests for the embed stage.

sentence-transformers is a heavy dependency, so we mock ``_load_model`` to
return a fake model that produces deterministic vectors. This lets the test
suite stay fast (<1s) and not require a model download.

Remote-backend tests mock ``httpx.Client`` to avoid network I/O.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import httpx
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


# ---------------------------------------------------------------------------
# Remote backend tests
# ---------------------------------------------------------------------------

_DIM = 64


def _openai_response(texts: list[str], dim: int = _DIM) -> dict:
    """Build a minimal OpenAI-compatible /v1/embeddings response."""
    return {
        "data": [
            {"embedding": [float(i)] * dim, "index": i}
            for i in range(len(texts))
        ],
        "model": "test-model",
        "usage": {"prompt_tokens": sum(len(t.split()) for t in texts)},
    }


def _mock_httpx_post(captured_requests: list[dict], dim: int = _DIM):
    """Return a mock ``post`` that records calls and returns a valid response."""

    def post(url: str, *, json: dict, **kwargs):  # type: ignore[no-untyped-def]
        captured_requests.append({"url": url, "json": json})
        texts = json["input"]
        resp = MagicMock(spec=httpx.Response)
        resp.status_code = 200
        resp.json.return_value = _openai_response(texts, dim)
        resp.raise_for_status = MagicMock()
        resp.request = MagicMock()
        return resp

    return post


class TestChunkEmbedderRemote:
    """ChunkEmbedder with endpoint set (remote backend)."""

    def test_sends_correct_http_request(self) -> None:
        from retrieval_hub.ingestion import embed

        captured: list[dict] = []
        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.post = _mock_httpx_post(captured)

        with patch("retrieval_hub.ingestion.embed.httpx.Client", return_value=mock_client):
            embedder = embed.ChunkEmbedder(
                model_name="test-model",
                endpoint="http://vllm:8000",
                cache_dir=None,
            )
            chunks = [_make_chunk("first", 0), _make_chunk("second", 1)]
            vecs = embedder.embed_chunks(chunks)

        assert len(vecs) == 2
        assert len(vecs[0]) == _DIM

        req = captured[0]
        assert req["url"] == "http://vllm:8000/v1/embeddings"
        assert req["json"]["model"] == "test-model"
        assert req["json"]["encoding_format"] == "float"

    def test_prefix_applied_before_sending(self) -> None:
        from retrieval_hub.ingestion import embed

        captured: list[dict] = []
        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.post = _mock_httpx_post(captured)

        with patch("retrieval_hub.ingestion.embed.httpx.Client", return_value=mock_client):
            embedder = embed.ChunkEmbedder(
                model_name="m",
                endpoint="http://vllm:8000",
                cache_dir=None,
                document_prefix="doc: ",
            )
            embedder.embed_chunks([_make_chunk("hello", 0)])

        sent_texts = captured[0]["json"]["input"]
        assert sent_texts == ["doc: hello"]

    def test_batching_splits_large_input(self) -> None:
        from retrieval_hub.ingestion import embed

        captured: list[dict] = []
        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.post = _mock_httpx_post(captured)

        with patch("retrieval_hub.ingestion.embed.httpx.Client", return_value=mock_client):
            embedder = embed.ChunkEmbedder(
                model_name="m",
                endpoint="http://vllm:8000",
                cache_dir=None,
                batch_size=2,
                document_prefix="",
            )
            chunks = [_make_chunk(f"text-{i}", i) for i in range(5)]
            vecs = embedder.embed_chunks(chunks)

        assert len(vecs) == 5
        assert len(captured) == 3  # ceil(5/2) = 3 HTTP requests
        assert len(captured[0]["json"]["input"]) == 2
        assert len(captured[1]["json"]["input"]) == 2
        assert len(captured[2]["json"]["input"]) == 1

    def test_dimension_property_remote(self) -> None:
        from retrieval_hub.ingestion import embed

        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.post = _mock_httpx_post([], dim=384)

        with patch("retrieval_hub.ingestion.embed.httpx.Client", return_value=mock_client):
            embedder = embed.ChunkEmbedder(
                model_name="m", endpoint="http://vllm:8000", cache_dir=None,
            )
            assert embedder.dimension == 384

    def test_dimension_cached_after_embed(self) -> None:
        from retrieval_hub.ingestion import embed

        captured: list[dict] = []
        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.post = _mock_httpx_post(captured, dim=256)

        with patch("retrieval_hub.ingestion.embed.httpx.Client", return_value=mock_client):
            embedder = embed.ChunkEmbedder(
                model_name="m",
                endpoint="http://vllm:8000",
                cache_dir=None,
                document_prefix="",
            )
            embedder.embed_chunks([_make_chunk("a", 0)])
            # Second call to .dimension should NOT probe the endpoint again
            dim = embedder.dimension

        assert dim == 256
        # Only 1 HTTP call (embed_chunks), no extra probe call
        assert len(captured) == 1

    def test_empty_input_returns_empty(self) -> None:
        from retrieval_hub.ingestion import embed

        embedder = embed.ChunkEmbedder(
            model_name="m", endpoint="http://vllm:8000", cache_dir=None,
        )
        assert embedder.embed_chunks([]) == []

    def test_endpoint_trailing_slash_stripped(self) -> None:
        from retrieval_hub.ingestion import embed

        captured: list[dict] = []
        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.post = _mock_httpx_post(captured)

        with patch("retrieval_hub.ingestion.embed.httpx.Client", return_value=mock_client):
            embedder = embed.ChunkEmbedder(
                model_name="m",
                endpoint="http://vllm:8000/",
                cache_dir=None,
                document_prefix="",
            )
            embedder.embed_chunks([_make_chunk("x", 0)])

        assert captured[0]["url"] == "http://vllm:8000/v1/embeddings"


class TestQueryEmbedderRemote:
    """QueryEmbedder with endpoint set (remote backend)."""

    def test_embed_single_query(self) -> None:
        from retrieval_hub.ingestion import embed

        captured: list[dict] = []
        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.post = _mock_httpx_post(captured)

        with patch("retrieval_hub.ingestion.embed.httpx.Client", return_value=mock_client):
            embedder = embed.QueryEmbedder(
                model_name="m", endpoint="http://vllm:8000", cache_dir=None,
            )
            vec = embedder.embed("what is hypertension")

        assert len(vec) == _DIM
        assert all(isinstance(v, float) for v in vec)
        sent_texts = captured[0]["json"]["input"]
        assert sent_texts == ["search_query: what is hypertension"]

    def test_custom_prefix_applied(self) -> None:
        from retrieval_hub.ingestion import embed

        captured: list[dict] = []
        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.post = _mock_httpx_post(captured)

        with patch("retrieval_hub.ingestion.embed.httpx.Client", return_value=mock_client):
            embedder = embed.QueryEmbedder(
                model_name="m",
                endpoint="http://vllm:8000",
                cache_dir=None,
                query_prefix="query: ",
            )
            embedder.embed("test query")

        assert captured[0]["json"]["input"] == ["query: test query"]

    def test_empty_prefix(self) -> None:
        from retrieval_hub.ingestion import embed

        captured: list[dict] = []
        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.post = _mock_httpx_post(captured)

        with patch("retrieval_hub.ingestion.embed.httpx.Client", return_value=mock_client):
            embedder = embed.QueryEmbedder(
                model_name="m",
                endpoint="http://vllm:8000",
                cache_dir=None,
                query_prefix="",
            )
            embedder.embed("raw text")

        assert captured[0]["json"]["input"] == ["raw text"]


class TestRemoteRetry:
    """Retry and error handling for the remote backend."""

    def test_retries_on_5xx(self) -> None:
        from retrieval_hub.ingestion import embed

        call_count = 0

        def flaky_post(url, *, json, **kwargs):  # type: ignore[no-untyped-def]
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                resp = MagicMock(spec=httpx.Response)
                resp.status_code = 503
                resp.request = MagicMock()
                return resp
            resp = MagicMock(spec=httpx.Response)
            resp.status_code = 200
            resp.json.return_value = _openai_response(json["input"])
            resp.raise_for_status = MagicMock()
            resp.request = MagicMock()
            return resp

        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.post = flaky_post

        with (
            patch("retrieval_hub.ingestion.embed.httpx.Client", return_value=mock_client),
            patch("retrieval_hub.ingestion.embed._backoff_sleep"),
        ):
            embedder = embed.QueryEmbedder(
                model_name="m", endpoint="http://vllm:8000", cache_dir=None,
            )
            vec = embedder.embed("test")

        assert call_count == 3
        assert len(vec) == _DIM

    def test_raises_after_max_retries(self) -> None:
        from retrieval_hub.ingestion import embed

        def always_503(url, *, json, **kwargs):  # type: ignore[no-untyped-def]
            resp = MagicMock(spec=httpx.Response)
            resp.status_code = 503
            resp.request = MagicMock()
            return resp

        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.post = always_503

        with (
            patch("retrieval_hub.ingestion.embed.httpx.Client", return_value=mock_client),
            patch("retrieval_hub.ingestion.embed._backoff_sleep"),
        ):
            embedder = embed.QueryEmbedder(
                model_name="m", endpoint="http://vllm:8000", cache_dir=None,
            )
            with pytest.raises(httpx.HTTPStatusError, match="503"):
                embedder.embed("test")

    def test_retries_on_timeout(self) -> None:
        from retrieval_hub.ingestion import embed

        call_count = 0

        def timeout_then_ok(url, *, json, **kwargs):  # type: ignore[no-untyped-def]
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise httpx.ReadTimeout("read timed out")
            resp = MagicMock(spec=httpx.Response)
            resp.status_code = 200
            resp.json.return_value = _openai_response(json["input"])
            resp.raise_for_status = MagicMock()
            resp.request = MagicMock()
            return resp

        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.post = timeout_then_ok

        with (
            patch("retrieval_hub.ingestion.embed.httpx.Client", return_value=mock_client),
            patch("retrieval_hub.ingestion.embed._backoff_sleep"),
        ):
            embedder = embed.QueryEmbedder(
                model_name="m", endpoint="http://vllm:8000", cache_dir=None,
            )
            vec = embedder.embed("test")

        assert call_count == 2
        assert len(vec) == _DIM


class TestLocalFallbackUnchanged:
    """Confirm the local backend is untouched when endpoint is None."""

    def test_chunk_embedder_no_endpoint_uses_local(self) -> None:
        from retrieval_hub.ingestion import embed

        with patch.object(embed, "_load_model", return_value=_fake_model(768)):
            embedder = embed.ChunkEmbedder(cache_dir=None)
            assert embedder._backend == "local"
            vecs = embedder.embed_chunks([_make_chunk("hello", 0)])

        assert len(vecs) == 1
        assert len(vecs[0]) == 768

    def test_query_embedder_no_endpoint_uses_local(self) -> None:
        from retrieval_hub.ingestion import embed

        with patch.object(embed, "_load_model", return_value=_fake_model(768)):
            embedder = embed.QueryEmbedder(cache_dir=None)
            assert embedder._backend == "local"
            vec = embedder.embed("test")

        assert len(vec) == 768
