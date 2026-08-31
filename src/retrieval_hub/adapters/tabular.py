"""Tabular-family adapter for structured row-based data.

Extends ``DocumentAdapter`` with a ``table_context`` refine strategy
that returns rows sharing the same doc_title (table/file), giving
the user related records from the same dataset.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from retrieval_hub.adapters.document import DocumentAdapter

if TYPE_CHECKING:
    from retrieval_hub.retrieval.api import RefineOutput

logger = logging.getLogger(__name__)


class TabularAdapter(DocumentAdapter):
    """Adapter for tabular-family sources with row-context refinement."""

    def refine(
        self,
        *,
        doc_title: str,
        chunk_index: int,
        query: str,
        window: int,
        request_id: str,
        strategy: str = "table_context",
        max_context_tokens: int | None = None,
    ) -> RefineOutput:
        if strategy == "table_context":
            return self._table_context_refine(
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

    def _table_context_refine(
        self,
        *,
        doc_title: str,
        chunk_index: int,
        request_id: str,
        max_context_tokens: int | None = None,
    ) -> RefineOutput:
        """Return nearby rows from the same table/file."""
        from retrieval_hub.retrieval.api import RefineOutput, RetrievalResult

        table = self.physical_index.location
        rows = self._fetch_table_rows(table, doc_title, chunk_index)

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
            "tabular.table_context_refine doc=%s chunks=%d",
            doc_title, len(results),
        )
        return RefineOutput(
            results=results,
            truncated=max_context_tokens is not None and len(results) < len(rows),
            total_chunks=len(rows),
        )

    def _fetch_table_rows(
        self, table: str, doc_title: str, origin_chunk_index: int,
        window: int = 10,
    ) -> list[dict]:
        """Fetch rows near the origin from the same table, ordered by chunk_index."""
        import psycopg

        from retrieval_hub.adapters.document import _psycopg_url

        sql = (
            f"SELECT id, chunk_text, chunk_tokens, doc_title, doc_url, "
            f"doc_section, chunk_index "
            f"FROM {table} "
            f"WHERE doc_title = %s "
            f"AND chunk_index BETWEEN %s AND %s "
            f"ORDER BY chunk_index"
        )

        low = max(0, origin_chunk_index - window)
        high = origin_chunk_index + window

        with psycopg.connect(_psycopg_url(self._vectors_db_url)) as conn:
            with conn.cursor() as cur:
                cur.execute(sql, (doc_title, low, high))
                cols = [d.name for d in cur.description]
                return [dict(zip(cols, row, strict=True)) for row in cur.fetchall()]
