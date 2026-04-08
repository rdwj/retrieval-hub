"""Tests for the normalize stage.

Pure text transformations — no external deps.
"""

from __future__ import annotations

from retrieval_hub.ingestion.normalize import (
    NormalizedDocument,
    find_section_for_offset,
    normalize_document,
)
from retrieval_hub.ingestion.parse import ParsedDocument, ParsedSection


def _make_parsed(text: str) -> ParsedDocument:
    return ParsedDocument(
        url="https://example.com/doc",
        title="Example",
        text=text,
        content_type="text/html",
        sections=[],
        metadata={"parser": "test"},
    )


def test_normalize_drops_empty_document() -> None:
    parsed = _make_parsed("")
    assert normalize_document(parsed) is None


def test_normalize_drops_too_short_document() -> None:
    parsed = _make_parsed("Too short.")
    assert normalize_document(parsed) is None


def test_normalize_strips_boilerplate_lines() -> None:
    text = (
        "Skip to main content\n"
        "On this page\n"
        "This is the real content that is long enough to survive the threshold "
        "by including several sentences of substance that actually describe "
        "something. It should be the only thing left after normalization.\n"
        "© 2026 Red Hat, Inc. All rights reserved.\n"
        "Privacy Statement\n"
    )
    parsed = _make_parsed(text)
    result = normalize_document(parsed)
    assert result is not None
    assert "Skip to main content" not in result.text
    assert "On this page" not in result.text
    assert "© 2026" not in result.text
    assert "real content" in result.text


def test_normalize_preserves_metadata_and_adds_normalized_flag() -> None:
    long_text = (
        "This is a long enough body of content to survive the normalization "
        "threshold. We need enough characters to clear the minimum. Adding "
        "another sentence to make sure we are well past the 200 character "
        "cutoff and the text will actually survive normalization cleanly."
    )
    parsed = _make_parsed(long_text)
    result = normalize_document(parsed)
    assert result is not None
    assert result.metadata["parser"] == "test"
    assert result.metadata["normalized"] == "true"
    assert isinstance(result, NormalizedDocument)


def test_find_section_for_offset_returns_none_before_any_heading() -> None:
    sections = [
        ParsedSection(heading="First", level=1, char_offset=100),
        ParsedSection(heading="Second", level=1, char_offset=200),
    ]
    assert find_section_for_offset(sections, 50) is None


def test_find_section_for_offset_returns_most_recent_preceding() -> None:
    sections = [
        ParsedSection(heading="First", level=1, char_offset=100),
        ParsedSection(heading="Second", level=1, char_offset=200),
        ParsedSection(heading="Third", level=1, char_offset=300),
    ]
    assert find_section_for_offset(sections, 150) == "First"
    assert find_section_for_offset(sections, 250) == "Second"
    assert find_section_for_offset(sections, 350) == "Third"


def test_find_section_for_offset_handles_empty_list() -> None:
    assert find_section_for_offset([], 100) is None
