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
from typing import TYPE_CHECKING, Any

from retrieval_hub.adapters.base import SourceAdapter
from retrieval_hub.models import PhysicalIndex, RecipeVersion, Source
from retrieval_hub.models.enums import PhysicalIndexBackend

if TYPE_CHECKING:
    from retrieval_hub.retrieval.api import RefineOutput

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
        from retrieval_hub.ingestion.embed import QueryEmbedder
        from retrieval_hub.retrieval.api import RetrievalResult

        embedder = QueryEmbedder(
            model_name=self._embedding_model_name(),
            query_prefix=self._query_prefix(),
            prompt_name=self._query_prompt_name(),
        )
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
                    chunk_index=row["chunk_index"],
                    physical_index_id=self.physical_index.id,
                    recipe_version=self.recipe_version.version_number,
                    request_id=request_id,
                )
            )
        return results

    # -- the refine entry point --------------------------------------------

    def refine(
        self,
        *,
        doc_title: str,
        chunk_index: int,
        query: str,
        window: int,
        request_id: str,
        strategy: str = "adjacent",
        max_context_tokens: int | None = None,
    ) -> RefineOutput:
        from retrieval_hub.retrieval.api import RefineOutput, RetrievalResult

        if strategy == "section":
            rows = self._resolve_section_chunks(doc_title, chunk_index)
        else:
            rows = self._adjacent_chunks(doc_title, chunk_index, window)

        total_chunks = len(rows)

        if max_context_tokens is not None:
            rows = self._truncate_to_budget(rows, chunk_index, max_context_tokens)

        truncated = len(rows) < total_chunks

        results = [
            RetrievalResult(
                text=row["chunk_text"],
                score=1.0,
                doc_title=row["doc_title"] or "",
                doc_url=row["doc_url"] or "",
                doc_section=row["doc_section"],
                chunk_index=row["chunk_index"],
                physical_index_id=self.physical_index.id,
                recipe_version=self.recipe_version.version_number,
                request_id=request_id,
            )
            for row in rows
        ]

        return RefineOutput(
            results=results,
            truncated=truncated,
            total_chunks=total_chunks if truncated else None,
        )

    # -- internals --------------------------------------------------------

    def _query_prefix(self) -> str:
        """Pull the query prefix from the recipe, defaulting to Nomic's."""
        content = self.recipe_version.content or {}
        embedding = content.get("embedding") or {}
        return embedding.get("query_prefix", "search_query: ")

    def _query_prompt_name(self) -> str | None:
        """Pull the prompt_name from the recipe for models that use it."""
        content = self.recipe_version.content or {}
        embedding = content.get("embedding") or {}
        return embedding.get("query_prompt_name")

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

    def _adjacent_chunks(
        self,
        doc_title: str,
        chunk_index: int,
        window: int,
    ) -> list[dict[str, Any]]:
        """Fetch chunks adjacent to ``chunk_index`` within the same document."""
        import psycopg

        table = self.physical_index.location
        lo = max(0, chunk_index - window)
        hi = chunk_index + window

        sql = (
            f"SELECT id, chunk_text, chunk_tokens, doc_title, doc_url, doc_section, chunk_index "
            f"FROM {table} "
            f"WHERE doc_title = %s AND chunk_index BETWEEN %s AND %s "
            f"ORDER BY chunk_index"
        )

        with psycopg.connect(_psycopg_url(self._vectors_db_url)) as conn:
            with conn.cursor() as cur:
                cur.execute(sql, (doc_title, lo, hi))
                cols = [desc.name for desc in cur.description or []]
                rows = cur.fetchall()
        return [dict(zip(cols, row, strict=True)) for row in rows]

    def _get_chunk(
        self,
        doc_title: str,
        chunk_index: int,
    ) -> dict[str, Any] | None:
        """Fetch a single chunk by document title and index."""
        import psycopg

        table = self.physical_index.location

        sql = (
            f"SELECT id, chunk_text, chunk_tokens, doc_title, doc_url, doc_section, chunk_index "
            f"FROM {table} "
            f"WHERE doc_title = %s AND chunk_index = %s "
            f"LIMIT 1"
        )

        with psycopg.connect(_psycopg_url(self._vectors_db_url)) as conn:
            with conn.cursor() as cur:
                cur.execute(sql, (doc_title, chunk_index))
                cols = [desc.name for desc in cur.description or []]
                row = cur.fetchone()
        if row is None:
            return None
        return dict(zip(cols, row, strict=True))

    def _section_chunks(
        self,
        doc_title: str,
        doc_section: str,
    ) -> list[dict[str, Any]]:
        """Fetch all chunks from the given section within a document."""
        import psycopg

        table = self.physical_index.location

        sql = (
            f"SELECT id, chunk_text, chunk_tokens, doc_title, doc_url, doc_section, chunk_index "
            f"FROM {table} "
            f"WHERE doc_title = %s AND doc_section = %s "
            f"ORDER BY chunk_index"
        )

        with psycopg.connect(_psycopg_url(self._vectors_db_url)) as conn:
            with conn.cursor() as cur:
                cur.execute(sql, (doc_title, doc_section))
                cols = [desc.name for desc in cur.description or []]
                rows = cur.fetchall()
        return [dict(zip(cols, row, strict=True)) for row in rows]

    def _resolve_section_chunks(
        self,
        doc_title: str,
        chunk_index: int,
    ) -> list[dict[str, Any]]:
        """Look up the origin chunk's section, then fetch all chunks in that section."""
        origin = self._get_chunk(doc_title, chunk_index)
        if origin is None:
            return []
        doc_section = origin.get("doc_section")
        if not doc_section:
            # Chunk has no section -- fall back to returning just the origin
            return [origin]
        return self._section_chunks(doc_title, doc_section)

    def _truncate_to_budget(
        self,
        rows: list[dict[str, Any]],
        origin_chunk_index: int,
        max_tokens: int,
    ) -> list[dict[str, Any]]:
        """Keep the origin chunk and expand outward until the token budget is exhausted."""
        if not rows:
            return rows

        # Find the origin row's position in the sorted list
        origin_pos = None
        for i, row in enumerate(rows):
            if row["chunk_index"] == origin_chunk_index:
                origin_pos = i
                break

        if origin_pos is None:
            # Origin not in results (shouldn't happen); return all
            return rows

        total_tokens = sum(row.get("chunk_tokens", 0) for row in rows)
        if total_tokens <= max_tokens:
            return rows

        # Start with the origin chunk
        selected_positions = [origin_pos]
        budget_used = rows[origin_pos].get("chunk_tokens", 0)

        # Expand outward alternating before/after
        lo = origin_pos - 1
        hi = origin_pos + 1

        while lo >= 0 or hi < len(rows):
            # Try adding the chunk before
            if lo >= 0:
                cost = rows[lo].get("chunk_tokens", 0)
                if budget_used + cost <= max_tokens:
                    selected_positions.append(lo)
                    budget_used += cost
                else:
                    lo = -1  # Stop expanding in this direction
                lo -= 1

            # Try adding the chunk after
            if hi < len(rows):
                cost = rows[hi].get("chunk_tokens", 0)
                if budget_used + cost <= max_tokens:
                    selected_positions.append(hi)
                    budget_used += cost
                else:
                    hi = len(rows)  # Stop expanding in this direction
                hi += 1

        selected_positions.sort()
        return [rows[i] for i in selected_positions]

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
