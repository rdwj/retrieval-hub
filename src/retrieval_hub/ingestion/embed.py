"""Stage 5 of the ingestion pipeline: embed chunks.

Supports two backends:

- **local** (default): loads a ``sentence-transformers`` model on CPU.
  Suitable for small-corpus ingest runs on developer machines.
- **remote**: calls an OpenAI-compatible ``/v1/embeddings`` endpoint
  (vLLM, TEI, or any compatible server).  Activated by passing an
  ``endpoint`` URL to ``ChunkEmbedder`` / ``QueryEmbedder``.

Both backends share the same public interface so callers never need to
branch on the backend.

Two small but load-bearing details:

- We cache the model under ``.model_cache/`` so subsequent runs don't
  re-download. ``SENTENCE_TRANSFORMERS_HOME`` is set before importing the
  library when the caller asks for a cache dir.
- Both ``ChunkEmbedder`` (for ingestion) and ``QueryEmbedder`` (for the
  document adapter) live here so corpus and queries are guaranteed to share
  the exact same embedding code path.
"""

from __future__ import annotations

import logging
import os
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any

import httpx

if TYPE_CHECKING:
    from sentence_transformers import SentenceTransformer

    from retrieval_hub.ingestion.chunking.token_fixed import Chunk

logger = logging.getLogger(__name__)


DEFAULT_MODEL_NAME = "nomic-ai/nomic-embed-text-v1.5"
DEFAULT_DIMENSION = 768
DEFAULT_MODEL_CACHE_DIR = ".model_cache"

_REMOTE_TIMEOUT_S = 120.0
_REMOTE_MAX_RETRIES = 10
_REMOTE_BACKOFF_BASE_S = 1.0


def _remote_embed(
    endpoint: str,
    model_name: str,
    texts: list[str],
    *,
    timeout: float = _REMOTE_TIMEOUT_S,
) -> list[list[float]]:
    """Call an OpenAI-compatible ``/v1/embeddings`` endpoint with retry.

    Retries up to ``_REMOTE_MAX_RETRIES`` times on 5xx responses and
    transport-level timeouts, using exponential backoff.  Returns
    embeddings in the order matching ``texts``.
    """
    url = f"{endpoint}/v1/embeddings"
    payload: dict[str, Any] = {
        "model": model_name,
        "input": texts,
        "encoding_format": "float",
        "truncate_prompt_tokens": 512,
    }

    last_err: Exception | None = None
    for attempt in range(_REMOTE_MAX_RETRIES + 1):
        try:
            with httpx.Client(timeout=timeout) as client:
                resp = client.post(url, json=payload)

            if resp.status_code >= 500 or resp.status_code == 429:
                last_err = httpx.HTTPStatusError(
                    f"Server error {resp.status_code}",
                    request=resp.request,
                    response=resp,
                )
                if attempt < _REMOTE_MAX_RETRIES:
                    _backoff_sleep(attempt)
                    continue
                raise last_err

            resp.raise_for_status()
            body = resp.json()
            # Sort by index to guarantee ordering matches input
            items = sorted(body["data"], key=lambda d: d["index"])
            return [item["embedding"] for item in items]

        except (httpx.TimeoutException, httpx.ConnectError, httpx.RemoteProtocolError, httpx.ReadError) as exc:
            last_err = exc
            if attempt < _REMOTE_MAX_RETRIES:
                _backoff_sleep(attempt)
                continue
            raise

    # Should not reach here, but satisfy the type checker
    raise last_err  # type: ignore[misc]


def _backoff_sleep(attempt: int) -> None:
    delay = _REMOTE_BACKOFF_BASE_S * (2**attempt)
    logger.warning("Remote embedding attempt %d failed, retrying in %.1fs", attempt + 1, delay)
    time.sleep(delay)


def _configure_cache_dir(cache_dir: str | None) -> None:
    """Route sentence-transformers caches under ``cache_dir`` when given."""
    if not cache_dir:
        return
    abs_dir = str(Path(cache_dir).resolve())
    Path(abs_dir).mkdir(parents=True, exist_ok=True)
    os.environ.setdefault("SENTENCE_TRANSFORMERS_HOME", abs_dir)
    os.environ.setdefault("HF_HOME", abs_dir)


def _load_model(
    model_name: str, *, cache_dir: str | None
) -> SentenceTransformer:
    """Load and return a SentenceTransformer model, honoring the cache dir."""
    _configure_cache_dir(cache_dir)
    from sentence_transformers import SentenceTransformer

    logger.info("embed._load_model model=%s cache_dir=%s", model_name, cache_dir)
    return SentenceTransformer(model_name, trust_remote_code=True)


class ChunkEmbedder:
    """Batch-embed chunks with a local model or a remote endpoint.

    The embedder is created once per ingest run and reused across batches so
    the model only loads into memory one time.

    Parameters
    ----------
    endpoint:
        Base URL of an OpenAI-compatible embeddings service (e.g.
        ``http://vllm:8000``).  When set, the embedder calls
        ``{endpoint}/v1/embeddings`` instead of loading a local model.
    document_prefix:
        String prepended to each chunk before encoding.  Defaults to
        ``"search_document: "`` (the prefix Nomic v1.5 expects for corpus
        text).  Set to ``""`` for models like PubMedBERT that require no
        prefix.
    """

    def __init__(
        self,
        *,
        model_name: str = DEFAULT_MODEL_NAME,
        endpoint: str | None = None,
        cache_dir: str | None = DEFAULT_MODEL_CACHE_DIR,
        batch_size: int = 32,
        document_prefix: str = "search_document: ",
        prompt_name: str | None = None,
    ) -> None:
        self.model_name = model_name
        self.batch_size = batch_size
        self._document_prefix = document_prefix
        self._prompt_name = prompt_name

        if endpoint:
            self._backend = "remote"
            self._endpoint = endpoint.rstrip("/")
            self._remote_dim: int | None = None
        else:
            self._backend = "local"
            self._model = _load_model(model_name, cache_dir=cache_dir)

    @property
    def dimension(self) -> int:
        if self._backend == "remote":
            if self._remote_dim is not None:
                return self._remote_dim
            # Probe the endpoint with a short text to discover dimension
            vecs = _remote_embed(self._endpoint, self.model_name, ["dimension probe"])
            self._remote_dim = len(vecs[0])
            return self._remote_dim
        dim = self._model.get_sentence_embedding_dimension()
        if dim is None:
            raise RuntimeError(
                f"sentence-transformers model {self.model_name!r} reported no dimension"
            )
        return int(dim)

    def _apply_prefix(self, texts: list[str]) -> list[str]:
        """Prepend the document prefix (or prompt_name marker) to texts."""
        if self._prompt_name:
            # prompt_name is handled by sentence-transformers locally;
            # for remote, we have no equivalent so just pass raw texts
            return texts
        if self._document_prefix:
            return [f"{self._document_prefix}{t}" for t in texts]
        return texts

    def embed_chunks(self, chunks: list[Chunk]) -> list[list[float]]:
        """Return one embedding vector per chunk, preserving order."""
        if not chunks:
            return []
        texts = [c.text for c in chunks]

        if self._backend == "remote":
            prefixed = self._apply_prefix(texts)
            all_vectors: list[list[float]] = []
            batch_num = 0
            for i in range(0, len(prefixed), self.batch_size):
                batch = prefixed[i : i + self.batch_size]
                vecs = _remote_embed(self._endpoint, self.model_name, batch)
                all_vectors.extend(vecs)
                batch_num += 1
                if i + self.batch_size < len(prefixed):
                    # Periodic cooldown to prevent TEI memory buildup
                    if batch_num % 50 == 0:
                        logger.info("embed.cooldown after %d batches", batch_num)
                        time.sleep(5.0)
                    else:
                        time.sleep(0.5)
            if self._remote_dim is None and all_vectors:
                self._remote_dim = len(all_vectors[0])
            return all_vectors

        # Local backend
        encode_kwargs: dict = {
            "batch_size": self.batch_size,
            "convert_to_numpy": True,
            "normalize_embeddings": True,
            "show_progress_bar": False,
        }

        if self._prompt_name:
            encode_kwargs["prompt_name"] = self._prompt_name
            sentences = texts
        elif self._document_prefix:
            sentences = [f"{self._document_prefix}{t}" for t in texts]
        else:
            sentences = texts

        vectors = self._model.encode(sentences, **encode_kwargs)
        return [list(map(float, v)) for v in vectors]


class QueryEmbedder:
    """Embed a single query string with a local model or a remote endpoint.

    Uses the same model as ``ChunkEmbedder`` but the ``search_query: `` prefix
    that Nomic's instructions recommend for queries.

    Parameters
    ----------
    endpoint:
        Base URL of an OpenAI-compatible embeddings service.  When set,
        the embedder calls ``{endpoint}/v1/embeddings`` instead of
        loading a local model.
    query_prefix:
        String prepended to the query before encoding.  Defaults to
        ``"search_query: "`` (the prefix Nomic v1.5 expects for queries).
        Set to ``""`` for models like PubMedBERT that require no prefix.
    """

    def __init__(
        self,
        *,
        model_name: str = DEFAULT_MODEL_NAME,
        endpoint: str | None = None,
        cache_dir: str | None = DEFAULT_MODEL_CACHE_DIR,
        query_prefix: str = "search_query: ",
        prompt_name: str | None = None,
    ) -> None:
        self.model_name = model_name
        self._query_prefix = query_prefix
        self._prompt_name = prompt_name

        if endpoint:
            self._backend = "remote"
            self._endpoint = endpoint.rstrip("/")
        else:
            self._backend = "local"
            self._model = _load_model(model_name, cache_dir=cache_dir)

    def _apply_prefix(self, text: str) -> str:
        if self._prompt_name:
            return text
        if self._query_prefix:
            return f"{self._query_prefix}{text}"
        return text

    def embed(self, query_text: str) -> list[float]:
        if self._backend == "remote":
            prefixed = self._apply_prefix(query_text)
            vecs = _remote_embed(self._endpoint, self.model_name, [prefixed])
            return vecs[0]

        encode_kwargs: dict = {
            "convert_to_numpy": True,
            "normalize_embeddings": True,
            "show_progress_bar": False,
        }

        if self._prompt_name:
            encode_kwargs["prompt_name"] = self._prompt_name
            sentences = [query_text]
        elif self._query_prefix:
            sentences = [f"{self._query_prefix}{query_text}"]
        else:
            sentences = [query_text]

        vector = self._model.encode(sentences, **encode_kwargs)[0]
        return list(map(float, vector))
