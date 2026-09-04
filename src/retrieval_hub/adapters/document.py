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
    "postgresql+psycopg://retrievalhub:retrievalhub@127.0.0.1:5433/retrievalhub_vectors"
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
        embedding_endpoint: str | None = None,
    ) -> None:
        super().__init__(
            source=source,
            physical_index=physical_index,
            recipe_version=recipe_version,
        )
        self._vectors_db_url = vectors_db_url or get_default_vectors_db_url()
        self._resolved_endpoint = embedding_endpoint

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
        doc_section: list[str] | None = None,
        scope_entity_id: str | None = None,
    ) -> list[Any]:
        if scope_entity_id is not None:
            raise ValueError(
                "scope_entity_id is only supported for graph-family sources."
            )

        from retrieval_hub.ingestion.embed import QueryEmbedder
        from retrieval_hub.retrieval.api import RetrievalResult

        embedder = QueryEmbedder(
            model_name=self._embedding_model_name(),
            endpoint=self._embedding_endpoint(),
            query_prefix=self._query_prefix(),
            prompt_name=self._query_prompt_name(),
        )
        query_vec = embedder.embed(query_text)

        rows = self._similarity_search(query_vec, top_k=top_k, doc_section=doc_section)

        results: list[RetrievalResult] = []
        for row in rows:
            results.append(
                RetrievalResult(
                    chunk_id=str(row["id"]),
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
        min_score: float | None = None,
    ) -> RefineOutput:
        from retrieval_hub.retrieval.api import RefineOutput, RetrievalResult

        if strategy == "section":
            rows = self._resolve_section_chunks(doc_title, chunk_index)
        elif strategy == "cross_reference":
            return self._cross_reference_refine(
                doc_title=doc_title,
                chunk_index=chunk_index,
                query=query,
                window=window,
                request_id=request_id,
                max_context_tokens=max_context_tokens,
            )
        elif strategy == "entity_arc":
            return self._entity_arc_refine(
                doc_title=doc_title,
                chunk_index=chunk_index,
                query=query,
                window=window,
                request_id=request_id,
                max_context_tokens=max_context_tokens,
                min_score=min_score,
            )
        else:
            rows = self._adjacent_chunks(doc_title, chunk_index, window)

        total_chunks = len(rows)

        if max_context_tokens is not None:
            rows = self._truncate_to_budget(rows, chunk_index, max_context_tokens)

        truncated = len(rows) < total_chunks

        results = [
            RetrievalResult(
                chunk_id=str(row["id"]),
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

    def get_chunk_by_id(self, chunk_id: str) -> dict[str, Any] | None:
        """Look up a single chunk by its UUID primary key."""
        import psycopg

        table = self.physical_index.location

        query = (
            f"SELECT id, chunk_text, chunk_tokens, doc_title, doc_url, doc_section, chunk_index "
            f"FROM {table} WHERE id = %s LIMIT 1"
        )

        with psycopg.connect(_psycopg_url(self._vectors_db_url)) as conn:
            with conn.cursor() as cur:
                cur.execute(query, (chunk_id,))
                cols = [desc.name for desc in cur.description or []]
                row = cur.fetchone()
        if row is None:
            return None
        return dict(zip(cols, row, strict=True))

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

    def _embedding_endpoint(self) -> str | None:
        """Return the embedding endpoint, preferring the registry-resolved URL."""
        if self._resolved_endpoint is not None:
            return self._resolved_endpoint
        content = self.recipe_version.content or {}
        embedding = content.get("embedding") or {}
        return embedding.get("endpoint")

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
        doc_section: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        """Run the ANN search against the pgvector table.

        Parameters
        ----------
        doc_section:
            Optional list of section names to restrict the search to.
            When provided, a ``WHERE doc_section = ANY(%s)`` clause is
            added so only chunks belonging to the given sections are
            considered.

        Returns a list of row dicts sorted by descending score.
        """
        import psycopg
        from pgvector.psycopg import register_vector

        table = self.physical_index.location
        logger.info(
            "document_adapter._similarity_search table=%s top_k=%d doc_section=%s",
            table,
            top_k,
            doc_section,
        )

        if doc_section is not None:
            sql = (
                f"SELECT id, chunk_text, doc_title, doc_url, doc_section, "
                f"chunk_index, 1 - (embedding <=> %s::vector) AS score "
                f"FROM {table} "
                f"WHERE doc_section = ANY(%s) "
                f"ORDER BY embedding <=> %s::vector "
                f"LIMIT %s"
            )
            params: tuple = (query_vec, doc_section, query_vec, top_k)
        else:
            sql = (
                f"SELECT id, chunk_text, doc_title, doc_url, doc_section, "
                f"chunk_index, 1 - (embedding <=> %s::vector) AS score "
                f"FROM {table} "
                f"ORDER BY embedding <=> %s::vector "
                f"LIMIT %s"
            )
            params = (query_vec, query_vec, top_k)

        with psycopg.connect(_psycopg_url(self._vectors_db_url)) as conn:
            register_vector(conn)
            with conn.cursor() as cur:
                cur.execute(sql, params)
                cols = [desc.name for desc in cur.description or []]
                rows = cur.fetchall()
        return [dict(zip(cols, row, strict=True)) for row in rows]

    def _filtered_similarity_search(
        self,
        query_vec: list[float],
        doc_titles: list[str],
        *,
        top_k: int,
    ) -> list[dict[str, Any]]:
        """Run an ANN search filtered to specific documents.

        Same as ``_similarity_search`` but restricted to chunks whose
        ``doc_title`` is in the provided list.  Returns rows sorted by
        descending score.
        """
        import psycopg
        from pgvector.psycopg import register_vector

        table = self.physical_index.location
        logger.info(
            "document_adapter._filtered_similarity_search table=%s "
            "doc_titles=%s top_k=%d",
            table,
            doc_titles,
            top_k,
        )

        sql = (
            f"SELECT id, chunk_text, chunk_tokens, doc_title, doc_url, "
            f"doc_section, chunk_index, "
            f"1 - (embedding <=> %s::vector) AS score "
            f"FROM {table} "
            f"WHERE doc_title = ANY(%s) "
            f"ORDER BY embedding <=> %s::vector "
            f"LIMIT %s"
        )

        with psycopg.connect(_psycopg_url(self._vectors_db_url)) as conn:
            register_vector(conn)
            with conn.cursor() as cur:
                cur.execute(sql, (query_vec, doc_titles, query_vec, top_k))
                cols = [desc.name for desc in cur.description or []]
                rows = cur.fetchall()
        return [dict(zip(cols, row, strict=True)) for row in rows]

    def _keyword_search_with_scores(
        self,
        patterns: list[str],
        doc_title: str,
        query_vec: list[float],
    ) -> list[dict[str, Any]]:
        """Keyword search within a document, with vector scores for ranking.

        Each pattern becomes an ILIKE condition OR'd together. The vector
        score is computed so keyword-only results can rank alongside vector
        results in the union.
        """
        import psycopg
        from pgvector.psycopg import register_vector

        table = self.physical_index.location

        def _escape_like(s: str) -> str:
            return s.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")

        ilike_clauses = " OR ".join(["chunk_text ILIKE %s"] * len(patterns))
        ilike_params = [f"%{_escape_like(p)}%" for p in patterns]

        sql = (
            f"SELECT id, chunk_text, chunk_tokens, doc_title, doc_url, "
            f"doc_section, chunk_index, "
            f"1 - (embedding <=> %s::vector) AS score "
            f"FROM {table} "
            f"WHERE doc_title = %s AND ({ilike_clauses}) "
            f"ORDER BY chunk_index"
        )

        with psycopg.connect(_psycopg_url(self._vectors_db_url)) as conn:
            register_vector(conn)
            with conn.cursor() as cur:
                cur.execute(sql, (query_vec, doc_title, *ilike_params))
                cols = [desc.name for desc in cur.description or []]
                rows = cur.fetchall()
        return [dict(zip(cols, row, strict=True)) for row in rows]

    def _resolve_entity_aliases(self, query: str) -> list[str]:
        """Resolve aliases for an entity name from the source's semantic context."""
        from retrieval_hub.schemas.semantic import SemanticContext

        raw_sc = self.source.semantic_context
        if raw_sc is None:
            return []
        try:
            sc = SemanticContext.model_validate(raw_sc)
        except Exception:
            return []

        for entity in sc.entities:
            if entity.name.lower() == query.lower():
                return entity.aliases
        return []

    def _resolve_cross_reference_targets(
        self,
        doc_title: str,
    ) -> list[str]:
        """Resolve which document titles are related to *doc_title* via the semantic layer.

        Pure logic -- no I/O.  Reads ``self.source.semantic_context``,
        walks entities and relationships, and returns the deduplicated
        list of doc_titles from related entities.
        """
        from retrieval_hub.schemas.semantic import SemanticContext

        raw_sc = self.source.semantic_context
        if raw_sc is None:
            return []
        try:
            sc = SemanticContext.model_validate(raw_sc)
        except Exception:
            logger.warning("Failed to parse semantic_context for cross-reference resolution", exc_info=True)
            return []

        entities_by_name: dict[str, Any] = {e.name: e for e in sc.entities}

        # Find which entity owns `doc_title`
        origin_entity_name: str | None = None
        for entity in sc.entities:
            if doc_title in entity.doc_titles:
                origin_entity_name = entity.name
                break

        if origin_entity_name is None:
            return []

        # Walk relationships to find related entity names
        target_entity_names: list[str] = []
        for rel in sc.relationships:
            if rel.directionality == "bidirectional":
                if rel.source_entity == origin_entity_name:
                    target_entity_names.append(rel.target_entity)
                elif rel.target_entity == origin_entity_name:
                    target_entity_names.append(rel.source_entity)
            else:
                # directed: only follow outgoing edges
                if rel.source_entity == origin_entity_name:
                    target_entity_names.append(rel.target_entity)

        # Collect doc_titles from target entities
        result: list[str] = []
        for name in target_entity_names:
            target_entity = entities_by_name.get(name)
            if target_entity is not None and target_entity.doc_titles:
                result.extend(target_entity.doc_titles)

        # Deduplicate while preserving order
        seen: set[str] = set()
        deduped: list[str] = []
        for title in result:
            if title not in seen:
                seen.add(title)
                deduped.append(title)
        return deduped

    def _truncate_cross_reference_to_budget(
        self,
        origin_row: dict[str, Any],
        xref_rows: list[dict[str, Any]],
        max_tokens: int,
    ) -> tuple[list[dict[str, Any]], bool]:
        """Keep the origin row and greedily add cross-reference rows within the token budget.

        ``xref_rows`` are expected to be sorted by score descending (from the
        similarity search).  Returns ``(combined_rows, was_truncated)``.
        """
        budget_used = origin_row.get("chunk_tokens", 0)
        kept: list[dict[str, Any]] = [origin_row]

        for row in xref_rows:
            cost = row.get("chunk_tokens", 0)
            if budget_used + cost <= max_tokens:
                kept.append(row)
                budget_used += cost
            else:
                return kept, True

        return kept, False

    def _cross_reference_refine(
        self,
        *,
        doc_title: str,
        chunk_index: int,
        query: str,
        window: int,
        request_id: str,
        max_context_tokens: int | None = None,
    ) -> RefineOutput:
        """Expand context by pulling semantically related chunks from cross-referenced documents."""
        from retrieval_hub.ingestion.embed import QueryEmbedder
        from retrieval_hub.retrieval.api import RefineOutput, RetrievalResult

        # 1. Fetch the origin chunk
        origin = self._get_chunk(doc_title, chunk_index)
        if origin is None:
            return RefineOutput(results=[], truncated=False)

        # 2. Resolve cross-reference targets
        target_doc_titles = self._resolve_cross_reference_targets(doc_title)
        if not target_doc_titles:
            return RefineOutput(
                results=[
                    RetrievalResult(
                        chunk_id=str(origin["id"]),
                        text=origin["chunk_text"],
                        score=1.0,
                        doc_title=origin["doc_title"] or "",
                        doc_url=origin["doc_url"] or "",
                        doc_section=origin["doc_section"],
                        chunk_index=origin["chunk_index"],
                        physical_index_id=self.physical_index.id,
                        recipe_version=self.recipe_version.version_number,
                        request_id=request_id,
                    )
                ],
                truncated=False,
            )

        # 3. Embed the query
        embedder = QueryEmbedder(
            model_name=self._embedding_model_name(),
            endpoint=self._embedding_endpoint(),
            query_prefix=self._query_prefix(),
            prompt_name=self._query_prompt_name(),
        )
        query_vec = embedder.embed(query)

        # 4. Filtered similarity search across related documents
        xref_rows = self._filtered_similarity_search(
            query_vec, target_doc_titles, top_k=window
        )

        # 5. Token budgeting
        truncated = False
        total_before_truncation = 1 + len(xref_rows)
        if max_context_tokens is not None:
            combined, truncated = self._truncate_cross_reference_to_budget(
                origin, xref_rows, max_context_tokens
            )
            if truncated:
                xref_rows = combined[1:]

        # 6. Build results: origin first, then cross-reference hits
        results: list[RetrievalResult] = [
            RetrievalResult(
                chunk_id=str(origin["id"]),
                text=origin["chunk_text"],
                score=1.0,
                doc_title=origin["doc_title"] or "",
                doc_url=origin["doc_url"] or "",
                doc_section=origin["doc_section"],
                chunk_index=origin["chunk_index"],
                physical_index_id=self.physical_index.id,
                recipe_version=self.recipe_version.version_number,
                request_id=request_id,
            )
        ]
        for row in xref_rows:
            results.append(
                RetrievalResult(
                    chunk_id=str(row["id"]),
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

        return RefineOutput(
            results=results,
            truncated=truncated,
            total_chunks=total_before_truncation if truncated else None,
        )

    def _entity_arc_refine(
        self,
        *,
        doc_title: str,
        chunk_index: int,
        query: str,
        window: int,
        request_id: str,
        max_context_tokens: int | None = None,
        min_score: float | None = None,
    ) -> RefineOutput:
        """Trace an entity's mentions across a document in structural order."""
        from retrieval_hub.ingestion.embed import QueryEmbedder
        from retrieval_hub.retrieval.api import RefineOutput, RetrievalResult

        # 1. Resolve aliases
        aliases = self._resolve_entity_aliases(query)
        keyword_patterns = [query] + aliases

        # 2. Embed the query
        embedder = QueryEmbedder(
            model_name=self._embedding_model_name(),
            endpoint=self._embedding_endpoint(),
            query_prefix=self._query_prefix(),
            prompt_name=self._query_prompt_name(),
        )
        query_vec = embedder.embed(query)

        # 3. Filtered ANN search within the document
        vector_rows = self._filtered_similarity_search(
            query_vec, [doc_title], top_k=window
        )

        # 4. Keyword search with vector scores
        keyword_rows = self._keyword_search_with_scores(
            keyword_patterns, doc_title, query_vec
        )

        # 5. Union by chunk_index, keeping higher score
        by_chunk: dict[int, dict[str, Any]] = {}
        for row in vector_rows:
            ci = row["chunk_index"]
            by_chunk[ci] = row
        for row in keyword_rows:
            ci = row["chunk_index"]
            if ci not in by_chunk or row["score"] > by_chunk[ci]["score"]:
                by_chunk[ci] = row

        candidates = list(by_chunk.values())

        # 6. Apply score floor
        effective_min_score = min_score if min_score is not None else 0.30
        candidates = [r for r in candidates if r["score"] >= effective_min_score]

        # 7. Sort by chunk_index for structural ordering
        candidates.sort(key=lambda r: r["chunk_index"])

        total_arc_mentions = len(candidates)

        # 8. Token budgeting
        truncated = False
        if max_context_tokens is not None:
            total_tokens = sum(r.get("chunk_tokens", 0) for r in candidates)
            if total_tokens > max_context_tokens:
                # Select top-scoring chunks within budget
                by_score = sorted(candidates, key=lambda r: r["score"], reverse=True)
                budget_used = 0
                selected_indices: set[int] = set()
                for row in by_score:
                    cost = row.get("chunk_tokens", 0)
                    if budget_used + cost <= max_context_tokens:
                        selected_indices.add(row["chunk_index"])
                        budget_used += cost
                # Re-sort by chunk_index
                candidates = [r for r in candidates if r["chunk_index"] in selected_indices]
                truncated = True

        # 9. Build results
        results = [
            RetrievalResult(
                chunk_id=str(row["id"]),
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
            for row in candidates
        ]

        return RefineOutput(
            results=results,
            truncated=truncated,
            total_chunks=total_arc_mentions if truncated else None,
        )
