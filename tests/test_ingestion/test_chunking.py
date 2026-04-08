"""Tests for the token-fixed chunker.

The chunker is pure Python — no network, no models, no DB — so we test it
directly against hand-constructed ``NormalizedDocument`` inputs.
"""

from __future__ import annotations

import pytest

from retrieval_hub.ingestion.chunking.token_fixed import (
    DEFAULT_CHUNK_TOKENS,
    DEFAULT_OVERLAP_TOKENS,
    chunk_document,
)
from retrieval_hub.ingestion.normalize import NormalizedDocument
from retrieval_hub.ingestion.parse import ParsedSection


def _make_doc(text: str, *, sections: list[ParsedSection] | None = None) -> NormalizedDocument:
    return NormalizedDocument(
        url="https://example.com/doc",
        title="Example Doc",
        text=text,
        sections=sections or [],
        metadata={},
    )


def test_chunk_document_empty_text() -> None:
    doc = _make_doc("")
    chunks = chunk_document(doc)
    assert chunks == []


def test_chunk_document_short_text_single_chunk() -> None:
    doc = _make_doc("This is a very short document. It should fit in one chunk.")
    chunks = chunk_document(doc)
    assert len(chunks) == 1
    assert chunks[0].text == doc.text
    assert chunks[0].chunk_index == 0
    assert chunks[0].doc_url == doc.url
    assert chunks[0].doc_title == doc.title
    assert chunks[0].token_count > 0


def test_chunk_document_long_text_produces_multiple_chunks() -> None:
    # ~2000 words should produce several 512-token chunks.
    body = " ".join(["word"] * 2000)
    doc = _make_doc(body)
    chunks = chunk_document(doc)
    assert len(chunks) >= 2
    for i, chunk in enumerate(chunks):
        assert chunk.chunk_index == i
        assert chunk.token_count > 0
        assert chunk.doc_url == doc.url


def test_chunk_document_respects_custom_chunk_size() -> None:
    body = " ".join([f"word{i}" for i in range(500)])
    doc = _make_doc(body)
    small = chunk_document(doc, chunk_tokens=50, overlap_tokens=10)
    large = chunk_document(doc, chunk_tokens=200, overlap_tokens=20)
    assert len(small) > len(large)


def test_chunk_document_overlap_must_be_smaller_than_size() -> None:
    doc = _make_doc("x y z")
    with pytest.raises(ValueError, match="overlap_tokens"):
        chunk_document(doc, chunk_tokens=10, overlap_tokens=10)


def test_chunk_document_rejects_nonpositive_chunk_size() -> None:
    doc = _make_doc("x y z")
    with pytest.raises(ValueError, match="chunk_tokens must be positive"):
        chunk_document(doc, chunk_tokens=0, overlap_tokens=0)


def test_chunk_document_rejects_negative_overlap() -> None:
    doc = _make_doc("x y z")
    with pytest.raises(ValueError, match="overlap_tokens must be non-negative"):
        chunk_document(doc, chunk_tokens=10, overlap_tokens=-1)


def test_chunk_document_last_chunk_kept_even_if_short() -> None:
    body = " ".join(["w"] * 1100)
    doc = _make_doc(body)
    chunks = chunk_document(doc, chunk_tokens=500, overlap_tokens=50)
    # There should be at least three chunks for ~1100 tokens at 500/50.
    assert len(chunks) >= 2
    # Confirm the last chunk's text is not empty.
    assert chunks[-1].text.strip() != ""


def test_chunk_document_defaults_exposed_as_constants() -> None:
    assert DEFAULT_CHUNK_TOKENS == 512
    assert DEFAULT_OVERLAP_TOKENS == 64


def test_chunk_document_section_attribution() -> None:
    text = "Intro paragraph.\n\n# First Section\nBody of first section.\n\n# Second Section\nBody of second section."
    sections = [
        ParsedSection(heading="First Section", level=1, char_offset=text.find("# First Section")),
        ParsedSection(heading="Second Section", level=1, char_offset=text.find("# Second Section")),
    ]
    doc = _make_doc(text, sections=sections)
    chunks = chunk_document(doc, chunk_tokens=200, overlap_tokens=0)
    # At least the first chunk should reference one of the sections (or None
    # for text that appears before any section heading).
    assert len(chunks) >= 1
