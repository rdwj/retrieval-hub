"""Stage 6 of the ingestion pipeline: write embedded chunks to pgvector.

This module owns the one pgvector physical index table that step 4 produces.
It handles table creation (idempotent), bulk insert of chunks+embeddings, and
a few helpers for the script to report on the table after the write.

Kept deliberately thin: no retries, no transactions beyond the single insert,
no upsert semantics. Re-running the ingest script truncates the table and
writes again (see ``write_chunks``'s ``replace`` flag). Production ingestion
runners will do better.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from retrieval_hub.ingestion.chunking.token_fixed import Chunk

logger = logging.getLogger(__name__)


CREATE_EXTENSION_SQL = "CREATE EXTENSION IF NOT EXISTS vector"


def _create_table_sql(table: str, dimension: int) -> str:
    """Return the DDL for the per-source pgvector table."""
    return (
        f"CREATE TABLE IF NOT EXISTS {table} ("
        "id UUID PRIMARY KEY,"
        "chunk_text TEXT NOT NULL,"
        "chunk_tokens INT NOT NULL,"
        "doc_title TEXT,"
        "doc_url TEXT,"
        "doc_section TEXT,"
        "chunk_index INT NOT NULL,"
        f"embedding VECTOR({dimension}) NOT NULL"
        ")"
    )


@dataclass
class WriteStats:
    """Simple summary of a write stage run."""

    table: str
    rows_written: int
    total_tokens: int


def _psycopg_url(sqla_url: str) -> str:
    """Convert a SQLAlchemy URL into a plain libpq/psycopg URL."""
    if sqla_url.startswith("postgresql+psycopg://"):
        return "postgresql://" + sqla_url[len("postgresql+psycopg://") :]
    if sqla_url.startswith("postgres+psycopg://"):
        return "postgresql://" + sqla_url[len("postgres+psycopg://") :]
    return sqla_url


def ensure_pgvector_schema(vectors_db_url: str, table: str, dimension: int) -> None:
    """Ensure the vector extension and the target table exist."""
    import psycopg

    with psycopg.connect(_psycopg_url(vectors_db_url)) as conn:
        with conn.cursor() as cur:
            cur.execute(CREATE_EXTENSION_SQL)
            cur.execute(_create_table_sql(table, dimension))
        conn.commit()
    logger.info(
        "write.ensure_pgvector_schema table=%s dimension=%d ok", table, dimension
    )


def write_chunks(
    vectors_db_url: str,
    table: str,
    chunks: list[Chunk],
    embeddings: list[list[float]],
    *,
    replace: bool = True,
) -> WriteStats:
    """Write chunks + embeddings to the pgvector table. Returns a stats struct."""
    import uuid as _uuid

    import psycopg
    from pgvector.psycopg import register_vector

    if len(chunks) != len(embeddings):
        raise ValueError(
            f"chunks and embeddings must line up 1:1: "
            f"{len(chunks)} chunks vs {len(embeddings)} embeddings"
        )

    total_tokens = sum(c.token_count for c in chunks)

    with psycopg.connect(_psycopg_url(vectors_db_url)) as conn:
        register_vector(conn)
        with conn.cursor() as cur:
            if replace:
                cur.execute(f"DELETE FROM {table}")
            insert_sql = (
                f"INSERT INTO {table} "
                "(id, chunk_text, chunk_tokens, doc_title, doc_url, "
                "doc_section, chunk_index, embedding) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s)"
            )
            for chunk, vector in zip(chunks, embeddings, strict=True):
                cur.execute(
                    insert_sql,
                    (
                        str(_uuid.uuid4()),
                        chunk.text,
                        chunk.token_count,
                        chunk.doc_title,
                        chunk.doc_url,
                        chunk.doc_section,
                        chunk.chunk_index,
                        vector,
                    ),
                )
        conn.commit()

    logger.info(
        "write.write_chunks table=%s rows=%d tokens=%d",
        table,
        len(chunks),
        total_tokens,
    )
    return WriteStats(
        table=table,
        rows_written=len(chunks),
        total_tokens=total_tokens,
    )


def count_rows(vectors_db_url: str, table: str) -> int:
    """Return the number of rows currently in the table."""
    import psycopg

    with psycopg.connect(_psycopg_url(vectors_db_url)) as conn:
        with conn.cursor() as cur:
            cur.execute(f"SELECT COUNT(*) FROM {table}")
            result = cur.fetchone()
    return int(result[0]) if result else 0
