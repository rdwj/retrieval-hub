"""Token-fixed chunker with overlap.

Implements stage 4 of the ingestion pipeline for the ``document`` family in
the simplest-that-could-possibly-work form: encode the normalized text with
tiktoken, slide a fixed-size window over the token sequence, and decode each
window back to a text chunk. A configurable overlap is carried from one chunk
to the next so no semantic unit is entirely split across chunks.

Design notes:
- We use ``tiktoken`` with the ``cl100k_base`` encoding. It's deterministic,
  widely available, and close enough to the real tokenizer of the embedding
  model for budgeting purposes. (The embedding model has its own tokenizer;
  the token count we track here is a conservative estimator for recipe
  parameters and cost reporting, not the exact number the embedding model
  sees.)
- The chunker takes a normalized document and returns ``Chunk`` items with
  the doc-level lineage fields populated (title, url, section path). The
  embed stage consumes these directly.
- The last chunk is kept even if it's shorter than the target size, so we
  don't silently lose the tail of short documents.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import tiktoken

from retrieval_hub.ingestion.normalize import NormalizedDocument, find_section_for_offset

logger = logging.getLogger(__name__)


DEFAULT_ENCODING_NAME = "cl100k_base"
DEFAULT_CHUNK_TOKENS = 512
DEFAULT_OVERLAP_TOKENS = 64


@dataclass
class Chunk:
    """One retrievable unit. Ready to be embedded and written."""

    text: str
    token_count: int
    chunk_index: int
    doc_url: str
    doc_title: str
    doc_section: str | None


def chunk_document(
    doc: NormalizedDocument,
    *,
    chunk_tokens: int = DEFAULT_CHUNK_TOKENS,
    overlap_tokens: int = DEFAULT_OVERLAP_TOKENS,
    encoding_name: str = DEFAULT_ENCODING_NAME,
) -> list[Chunk]:
    """Split ``doc.text`` into fixed-size token windows with overlap."""
    if chunk_tokens <= 0:
        raise ValueError(f"chunk_tokens must be positive, got {chunk_tokens}")
    if overlap_tokens < 0:
        raise ValueError(f"overlap_tokens must be non-negative, got {overlap_tokens}")
    if overlap_tokens >= chunk_tokens:
        raise ValueError(
            f"overlap_tokens ({overlap_tokens}) must be smaller than "
            f"chunk_tokens ({chunk_tokens})"
        )

    encoding = tiktoken.get_encoding(encoding_name)
    token_ids = encoding.encode(doc.text)
    total_tokens = len(token_ids)

    if total_tokens == 0:
        logger.info("chunk.chunk_document url=%s empty_text", doc.url)
        return []

    stride = chunk_tokens - overlap_tokens
    chunks: list[Chunk] = []
    index = 0
    start = 0
    while start < total_tokens:
        end = min(start + chunk_tokens, total_tokens)
        window = token_ids[start:end]
        chunk_text = encoding.decode(window)
        # Estimate doc-offset by re-encoding the first part and looking at
        # where the decoded chunk appears. This is good enough for section
        # attribution on the output and cheap.
        offset = doc.text.find(chunk_text[:32]) if chunk_text else 0
        if offset < 0:
            offset = 0
        section = find_section_for_offset(doc.sections, offset)

        chunks.append(
            Chunk(
                text=chunk_text,
                token_count=len(window),
                chunk_index=index,
                doc_url=doc.url,
                doc_title=doc.title,
                doc_section=section,
            )
        )

        if end == total_tokens:
            break
        start += stride
        index += 1

    logger.info(
        "chunk.chunk_document url=%s chunks=%d tokens=%d",
        doc.url,
        len(chunks),
        total_tokens,
    )
    return chunks
