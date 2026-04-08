"""Document-family adapter.

Given a ``document``-family source whose active physical index is a pgvector
table, answer retrieval queries with an ANN search over the chunk embeddings.
This is the first real adapter in the core library and establishes the shape
every future adapter follows.

The adapter embeds the query with the same model the recipe pins, looks up
the physical index row to find the pgvector table name, runs a top-k cosine
similarity search against that table, and returns normalized
``RetrievalResult`` items carrying the lineage handle.

Design notes:
- Embedding is done via ``retrieval_hub.ingestion.embed.QueryEmbedder`` so
  the ingest side and the query side share one code path. That guarantees
  the corpus and queries are embedded identically (same model, same
  dimension, same normalization).
- The pgvector connection is made lazily and the psycopg connection is
  opened per ``retrieve`` call. For step 4 (hand-run, small corpus) this is
  fine; a future production implementation would pool.
- The SQL is intentionally simple: we select by cosine distance and convert
  it to a similarity score with ``1 - distance``. No filters, no rerank.
"""

from __future__ import annotations

import logging
import os
from typing import Any

from retrieval_hub.adapters.base import SourceAdapter
from retrieval_hub.models import PhysicalIndex, RecipeVersion, Source
from retrieval_hub.models.enums import PhysicalIndexBackend

logger = logging.getLogger(__name__)


DEFAULT_VECTORS_DB_URL = (
    "postgresql+psycopg://retrievalhub:retrievalhub@localhost:5433/retrievalhub_vectors"
)
VECTORS_DB_URL_ENV_VAR = "RETRIEVAL_HUB_VECTORS_DB_URL"


def get_default_vectors_db_url() -> str:
    """Return the configured vectors-database URL or the dev default."""
    return os.environ.get(VECTORS_DB_URL_ENV_VAR, DEFAULT_VECTORS_DB_URL)


def _psycopg_url(sqla_url: str) -> str:
    """Convert a SQLAlchemy URL into a plain libpq/psycopg URL.

    SQLAlchemy URLs look like ``postgresql+psycopg://...``; psycopg's
    ``connect`` wants the driver suffix stripped.
    """
    if sqla_url.startswith("postgresql+psycopg://"):
        return "postgresql://" + sqla_url[len("postgresql+psycopg://") :]
    if sqla_url.startswith("postgres+psycopg://"):
        return "postgresql://" + sqla_url[len("postgres+psycopg://") :]
    return sqla_url


class DocumentAdapter(SourceAdapter):
    """Document-family adapter backed by a pgvector physical index."""

    def __init__(
        self,
        *,
        source: Source,
        physical_index: PhysicalIndex,
        recipe_version: RecipeVersion,
        vectors_db_url: str | None = None,
    ) -> None:
        super().__init__(
            source=source,
            physical_index=physical_index,
            recipe_version=recipe_version,
        )
        self._vectors_db_url = vectors_db_url or get_default_vectors_db_url()

        if physical_index.backend_kind != PhysicalIndexBackend.PGVECTOR:
            raise ValueError(
                f"DocumentAdapter only supports pgvector-backed physical indexes, "
                f"got {physical_index.backend_kind!r}"
            )

    # -- the retrieve entry point -----------------------------------------

    def retrieve(
        self,
        query_text: str,
        *,
        top_k: int,
        request_id: str,
    ) -> list[Any]:
        # Imported lazily to avoid pulling sentence-transformers into mere
        # package-imports during tests that don't exercise the real path.
        from retrieval_hub.ingestion.embed import QueryEmbedder
        from retrieval_hub.retrieval.api import RetrievalResult

        embedder = QueryEmbedder(model_name=self._embedding_model_name())
        query_vec = embedder.embed(query_text)

        rows = self._similarity_search(query_vec, top_k=top_k)

        results: list[RetrievalResult] = []
        for row in rows:
            results.append(
                RetrievalResult(
                    text=row["chunk_text"],
                    score=float(row["score"]),
                    doc_title=row["doc_title"] or "",
                    doc_url=row["doc_url"] or "",
                    doc_section=row["doc_section"],
                    physical_index_id=self.physical_index.id,
                    recipe_version=self.recipe_version.version_number,
                    request_id=request_id,
                )
            )
        return results

    # -- internals --------------------------------------------------------

    def _embedding_model_name(self) -> str:
        """Pull the embedding model name out of the recipe body."""
        content = self.recipe_version.content or {}
        embedding = content.get("embedding") or {}
        name = embedding.get("model")
        if not isinstance(name, str) or not name:
            raise ValueError(
                f"Recipe version {self.recipe_version.id} does not declare "
                f"an embedding.model. Recipe body: {content!r}"
            )
        return name

    def _similarity_search(
        self,
        query_vec: list[float],
        *,
        top_k: int,
    ) -> list[dict[str, Any]]:
        """Run the ANN search against the pgvector table.

        Returns a list of row dicts sorted by descending score.
        """
        import psycopg
        from pgvector.psycopg import register_vector

        table = self.physical_index.location
        logger.info(
            "document_adapter._similarity_search table=%s top_k=%d", table, top_k
        )

        sql = (
            f"SELECT id, chunk_text, doc_title, doc_url, doc_section, "
            f"chunk_index, 1 - (embedding <=> %s::vector) AS score "
            f"FROM {table} "
            f"ORDER BY embedding <=> %s::vector "
            f"LIMIT %s"
        )

        with psycopg.connect(_psycopg_url(self._vectors_db_url)) as conn:
            register_vector(conn)
            with conn.cursor() as cur:
                cur.execute(sql, (query_vec, query_vec, top_k))
                cols = [desc.name for desc in cur.description or []]
                rows = cur.fetchall()
        return [dict(zip(cols, row, strict=True)) for row in rows]
