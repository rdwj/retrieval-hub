"""Tests for the incremental embed-and-write checkpoint-resume logic."""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from retrieval_hub.ingestion.write import (
    WriteStats,
    clear_table,
    count_rows,
    ensure_pgvector_schema,
    get_existing_chunks,
    write_chunk_batch,
    write_chunks,
)


@dataclass
class FakeChunk:
    text: str
    token_count: int
    chunk_index: int
    doc_url: str
    doc_title: str
    doc_section: str | None = None


TABLE = "idx_checkpoint_test_v1"
DIMENSION = 4


def _make_chunks(n: int) -> list[FakeChunk]:
    return [
        FakeChunk(
            text=f"chunk {i} text content",
            token_count=5,
            chunk_index=i,
            doc_url=f"file:///doc_{i // 10}.md",
            doc_title=f"doc_{i // 10}",
        )
        for i in range(n)
    ]


def _make_embeddings(n: int) -> list[list[float]]:
    return [[float(i), 0.1, 0.2, 0.3] for i in range(n)]


@pytest.fixture()
def vectors_db(tmp_path):
    """Spin up a temporary SQLite-ish pgvector DB... or use the local postgres."""
    import os
    url = os.environ.get(
        "TEST_VECTORS_DB_URL",
        "postgresql+psycopg://retrievalhub:retrievalhub@127.0.0.1:5432/retrievalhub",
    )
    psycopg_url = url
    if psycopg_url.startswith("postgresql+psycopg://"):
        psycopg_url = "postgresql://" + psycopg_url[len("postgresql+psycopg://"):]

    import psycopg
    try:
        with psycopg.connect(psycopg_url) as conn:
            conn.execute("SELECT 1")
    except Exception:
        pytest.skip("No local postgres available for checkpoint test")

    ensure_pgvector_schema(url, TABLE, DIMENSION)
    clear_table(url, TABLE)
    yield url
    # Clean up
    try:
        import psycopg as pg
        with pg.connect(psycopg_url) as conn:
            conn.execute(f"DROP TABLE IF EXISTS {TABLE}")
            conn.commit()
    except Exception:
        pass


class TestWriteChunkBatch:
    def test_writes_batch(self, vectors_db):
        chunks = _make_chunks(5)
        embeddings = _make_embeddings(5)
        written = write_chunk_batch(vectors_db, TABLE, chunks, embeddings)
        assert written == 5
        assert count_rows(vectors_db, TABLE) == 5

    def test_multiple_batches_accumulate(self, vectors_db):
        chunks = _make_chunks(10)
        embeddings = _make_embeddings(10)

        write_chunk_batch(vectors_db, TABLE, chunks[:5], embeddings[:5])
        assert count_rows(vectors_db, TABLE) == 5

        write_chunk_batch(vectors_db, TABLE, chunks[5:], embeddings[5:])
        assert count_rows(vectors_db, TABLE) == 10


class TestGetExistingChunks:
    def test_empty_table(self, vectors_db):
        existing = get_existing_chunks(vectors_db, TABLE)
        assert existing == set()

    def test_returns_doc_url_chunk_index_pairs(self, vectors_db):
        chunks = _make_chunks(3)
        embeddings = _make_embeddings(3)
        write_chunk_batch(vectors_db, TABLE, chunks, embeddings)

        existing = get_existing_chunks(vectors_db, TABLE)
        assert len(existing) == 3
        assert (chunks[0].doc_url, chunks[0].chunk_index) in existing
        assert (chunks[2].doc_url, chunks[2].chunk_index) in existing


class TestClearTable:
    def test_clears_all_rows(self, vectors_db):
        chunks = _make_chunks(5)
        embeddings = _make_embeddings(5)
        write_chunk_batch(vectors_db, TABLE, chunks, embeddings)
        assert count_rows(vectors_db, TABLE) == 5

        clear_table(vectors_db, TABLE)
        assert count_rows(vectors_db, TABLE) == 0


class TestCheckpointResumeFlow:
    def test_simulated_interrupt_and_resume(self, vectors_db):
        """Simulate: embed 5/10 chunks, 'crash', resume with remaining 5."""
        all_chunks = _make_chunks(10)
        all_embeddings = _make_embeddings(10)

        # "First run" — write first 5 chunks then "crash"
        clear_table(vectors_db, TABLE)
        write_chunk_batch(vectors_db, TABLE, all_chunks[:5], all_embeddings[:5])
        assert count_rows(vectors_db, TABLE) == 5

        # "Resume" — check what's already there, skip those
        existing = get_existing_chunks(vectors_db, TABLE)
        assert len(existing) == 5

        pending = [
            (c, e)
            for c, e in zip(all_chunks, all_embeddings)
            if (c.doc_url, c.chunk_index) not in existing
        ]
        assert len(pending) == 5

        pending_chunks = [p[0] for p in pending]
        pending_embeddings = [p[1] for p in pending]
        write_chunk_batch(vectors_db, TABLE, pending_chunks, pending_embeddings)

        assert count_rows(vectors_db, TABLE) == 10

    def test_fresh_run_clears_partial(self, vectors_db):
        """A fresh run (resume=False) clears any partial data."""
        chunks = _make_chunks(5)
        embeddings = _make_embeddings(5)
        write_chunk_batch(vectors_db, TABLE, chunks, embeddings)
        assert count_rows(vectors_db, TABLE) == 5

        # Fresh run clears everything
        clear_table(vectors_db, TABLE)
        assert count_rows(vectors_db, TABLE) == 0

        # Then writes all chunks
        all_chunks = _make_chunks(10)
        all_embeddings = _make_embeddings(10)
        write_chunk_batch(vectors_db, TABLE, all_chunks, all_embeddings)
        assert count_rows(vectors_db, TABLE) == 10
