"""Process-family adapter for structured procedure documents.

Extends ``DocumentAdapter`` with a ``procedure`` refine strategy that
returns the full instruction sequence from any step hit, giving the
user complete procedure context rather than just adjacent chunks.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from retrieval_hub.adapters.document import DocumentAdapter

if TYPE_CHECKING:
    from retrieval_hub.retrieval.api import RefineOutput

logger = logging.getLogger(__name__)


class ProcessAdapter(DocumentAdapter):
    """Adapter for process-family sources with procedure-aware refinement."""

    def refine(
        self,
        *,
        doc_title: str,
        chunk_index: int,
        query: str,
        window: int,
        request_id: str,
        strategy: str = "procedure",
        max_context_tokens: int | None = None,
    ) -> RefineOutput:
        if strategy == "procedure":
            return self._procedure_refine(
                doc_title=doc_title,
                chunk_index=chunk_index,
                request_id=request_id,
                max_context_tokens=max_context_tokens,
            )
        return super().refine(
            doc_title=doc_title,
            chunk_index=chunk_index,
            query=query,
            window=window,
            request_id=request_id,
            strategy=strategy,
            max_context_tokens=max_context_tokens,
        )

    def _procedure_refine(
        self,
        *,
        doc_title: str,
        chunk_index: int,
        request_id: str,
        max_context_tokens: int | None = None,
    ) -> RefineOutput:
        """Return all instruction steps plus the header for a document."""
        from retrieval_hub.retrieval.api import RefineOutput, RetrievalResult

        table = self.physical_index.location
        rows = self._fetch_procedure_chunks(table, doc_title)

        results: list[RetrievalResult] = []
        for row in rows:
            results.append(
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
            )

        if max_context_tokens is not None:
            results = self._truncate_to_budget(
                results, chunk_index, max_context_tokens,
            )

        logger.info(
            "process.procedure_refine doc=%s chunks=%d",
            doc_title, len(results),
        )
        return RefineOutput(
            results=results,
            truncated=max_context_tokens is not None and len(results) < len(rows),
            total_chunks=len(rows),
        )

    def _fetch_procedure_chunks(
        self, table: str, doc_title: str,
    ) -> list[dict]:
        """Fetch header + instruction chunks for a document, ordered by chunk_index."""
        import psycopg

        from retrieval_hub.adapters.document import _psycopg_url

        sql = (
            f"SELECT id, chunk_text, chunk_tokens, doc_title, doc_url, "
            f"doc_section, chunk_index "
            f"FROM {table} "
            f"WHERE doc_title = %s "
            f"AND (doc_section LIKE 'instructions/%%' OR doc_section = 'header' "
            f"     OR doc_section LIKE 'header/%%') "
            f"ORDER BY chunk_index"
        )

        with psycopg.connect(_psycopg_url(self._vectors_db_url)) as conn:
            with conn.cursor() as cur:
                cur.execute(sql, (doc_title,))
                cols = [d.name for d in cur.description]
                return [dict(zip(cols, row, strict=True)) for row in cur.fetchall()]
