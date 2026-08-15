"""Stage 5 of the ingestion pipeline: embed chunks.

Step 4 uses ``sentence-transformers`` locally with ``nomic-ai/nomic-embed-text-v1.5``
(768 dimensions). It runs on CPU on the worker's machine, which is acceptable
for the small corpus this step targets. Production runners will call a vLLM
endpoint instead; same ``ChunkEmbedder`` interface, different backend.

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
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sentence_transformers import SentenceTransformer

    from retrieval_hub.ingestion.chunking.token_fixed import Chunk

logger = logging.getLogger(__name__)


DEFAULT_MODEL_NAME = "nomic-ai/nomic-embed-text-v1.5"
DEFAULT_DIMENSION = 768
DEFAULT_MODEL_CACHE_DIR = ".model_cache"


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
    """Batch-embed chunks with a sentence-transformers model.

    The embedder is created once per ingest run and reused across batches so
    the model only loads into memory one time.

    Parameters
    ----------
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
        cache_dir: str | None = DEFAULT_MODEL_CACHE_DIR,
        batch_size: int = 32,
        document_prefix: str = "search_document: ",
        prompt_name: str | None = None,
    ) -> None:
        self.model_name = model_name
        self.batch_size = batch_size
        self._document_prefix = document_prefix
        self._prompt_name = prompt_name
        self._model = _load_model(model_name, cache_dir=cache_dir)

    @property
    def dimension(self) -> int:
        dim = self._model.get_sentence_embedding_dimension()
        if dim is None:
            raise RuntimeError(
                f"sentence-transformers model {self.model_name!r} reported no dimension"
            )
        return int(dim)

    def embed_chunks(self, chunks: list[Chunk]) -> list[list[float]]:
        """Return one embedding vector per chunk, preserving order."""
        if not chunks:
            return []
        texts = [c.text for c in chunks]

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
    """Embed a single query string.

    Uses the same model as ``ChunkEmbedder`` but the ``search_query: `` prefix
    that Nomic's instructions recommend for queries.

    Parameters
    ----------
    query_prefix:
        String prepended to the query before encoding.  Defaults to
        ``"search_query: "`` (the prefix Nomic v1.5 expects for queries).
        Set to ``""`` for models like PubMedBERT that require no prefix.
    """

    def __init__(
        self,
        *,
        model_name: str = DEFAULT_MODEL_NAME,
        cache_dir: str | None = DEFAULT_MODEL_CACHE_DIR,
        query_prefix: str = "search_query: ",
        prompt_name: str | None = None,
    ) -> None:
        self.model_name = model_name
        self._query_prefix = query_prefix
        self._prompt_name = prompt_name
        self._model = _load_model(model_name, cache_dir=cache_dir)

    def embed(self, query_text: str) -> list[float]:
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
