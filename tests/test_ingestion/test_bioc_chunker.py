"""Tests for the BioC section-aware chunker."""

from __future__ import annotations

import tiktoken

from retrieval_hub.ingestion.chunking.bioc_section import (
    DEFAULT_SKIP_SECTIONS,
    BioCArticleMeta,
    chunk_bioc_document,
    extract_article_meta,
)
from retrieval_hub.ingestion.chunking.token_fixed import Chunk


def _make_passage(
    text: str,
    section_type: str = "INTRO",
    ptype: str = "paragraph",
    offset: int = 0,
    extra_infons: dict | None = None,
) -> dict:
    infons = {"section_type": section_type, "type": ptype}
    if extra_infons:
        infons.update(extra_infons)
    return {
        "bioctype": "BioCPassage",
        "offset": offset,
        "infons": infons,
        "text": text,
        "sentences": [],
        "annotations": [],
        "relations": [],
    }


def _make_front_passage(
    text: str = "Article Title",
    extra_infons: dict | None = None,
) -> dict:
    infons = {
        "section_type": "TITLE",
        "type": "front",
        "article-id_doi": "10.1234/test",
        "article-id_pmc": "PMC12345",
        "article-id_pmid": "98765",
        "kwd": "keyword1 keyword2 keyword3",
        "name_0": "surname:Smith;given-names:John",
        "name_1": "surname:Doe;given-names:Jane",
        "license": "CC BY",
        "year": "2025",
    }
    if extra_infons:
        infons.update(extra_infons)
    return {
        "bioctype": "BioCPassage",
        "offset": 0,
        "infons": infons,
        "text": text,
        "sentences": [],
        "annotations": [],
        "relations": [],
    }


def _wrap_bioc(passages: list[dict]) -> list[dict]:
    return [
        {
            "bioctype": "BioCCollection",
            "source": "PMC",
            "date": "20260101",
            "key": "pmc.key",
            "version": "1.0",
            "infons": {},
            "documents": [
                {
                    "bioctype": "BioCDocument",
                    "id": "PMC00001",
                    "infons": {},
                    "passages": passages,
                }
            ],
        }
    ]


def _token_count(text: str) -> int:
    enc = tiktoken.get_encoding("cl100k_base")
    return len(enc.encode(text))


DOC_URL = "https://example.com/article"
DOC_TITLE = "Test Article"


class TestBasicChunking:
    def test_produces_correctly_tagged_chunks(self) -> None:
        bioc = _wrap_bioc([
            _make_front_passage(),
            _make_passage("Abstract text here.", section_type="ABSTRACT", ptype="abstract"),
            _make_passage("Introduction", section_type="INTRO", ptype="title_1"),
            _make_passage("Intro paragraph one.", section_type="INTRO"),
            _make_passage("Methods", section_type="METHODS", ptype="title_1"),
            _make_passage("Methods paragraph one.", section_type="METHODS"),
        ])
        chunks = chunk_bioc_document(bioc, doc_url=DOC_URL, doc_title=DOC_TITLE)
        assert len(chunks) >= 3
        sections = [c.doc_section for c in chunks]
        assert "ABSTRACT" in sections
        assert "INTRO" in sections
        assert "METHODS" in sections

    def test_chunks_are_chunk_instances(self) -> None:
        bioc = _wrap_bioc([
            _make_front_passage(),
            _make_passage("Some text.", section_type="INTRO"),
        ])
        chunks = chunk_bioc_document(bioc, doc_url=DOC_URL, doc_title=DOC_TITLE)
        assert len(chunks) == 1
        assert isinstance(chunks[0], Chunk)
        assert chunks[0].doc_url == DOC_URL
        assert chunks[0].doc_title == DOC_TITLE
        assert chunks[0].chunk_index == 0

    def test_chunk_indices_are_sequential(self) -> None:
        words = " ".join(["word"] * 300)
        bioc = _wrap_bioc([
            _make_front_passage(),
            _make_passage(words, section_type="INTRO"),
            _make_passage(words, section_type="METHODS"),
            _make_passage(words, section_type="RESULTS"),
        ])
        chunks = chunk_bioc_document(
            bioc, doc_url=DOC_URL, doc_title=DOC_TITLE, chunk_tokens=100
        )
        for i, c in enumerate(chunks):
            assert c.chunk_index == i


class TestSectionBoundaries:
    def test_respected_by_default(self) -> None:
        small_text = "A short passage."
        bioc = _wrap_bioc([
            _make_front_passage(),
            _make_passage(small_text, section_type="INTRO"),
            _make_passage(small_text, section_type="METHODS"),
        ])
        chunks = chunk_bioc_document(
            bioc,
            doc_url=DOC_URL,
            doc_title=DOC_TITLE,
            chunk_tokens=512,
        )
        assert len(chunks) == 2
        assert chunks[0].doc_section == "INTRO"
        assert chunks[1].doc_section == "METHODS"

    def test_disabled_merges_across_sections(self) -> None:
        small_text = "A short passage."
        bioc = _wrap_bioc([
            _make_front_passage(),
            _make_passage(small_text, section_type="INTRO"),
            _make_passage(small_text, section_type="METHODS"),
        ])
        chunks = chunk_bioc_document(
            bioc,
            doc_url=DOC_URL,
            doc_title=DOC_TITLE,
            chunk_tokens=512,
            respect_section_boundaries=False,
        )
        assert len(chunks) == 1
        assert "A short passage." in chunks[0].text


class TestLargePassage:
    def test_oversized_passage_becomes_own_chunk(self) -> None:
        big_text = " ".join(["word"] * 800)
        bioc = _wrap_bioc([
            _make_front_passage(),
            _make_passage(big_text, section_type="INTRO"),
        ])
        chunks = chunk_bioc_document(
            bioc, doc_url=DOC_URL, doc_title=DOC_TITLE, chunk_tokens=100
        )
        assert len(chunks) >= 1
        assert "word" in chunks[0].text
        assert chunks[0].token_count > 100


class TestSmallDocument:
    def test_single_chunk(self) -> None:
        bioc = _wrap_bioc([
            _make_front_passage(),
            _make_passage("Short.", section_type="INTRO"),
        ])
        chunks = chunk_bioc_document(bioc, doc_url=DOC_URL, doc_title=DOC_TITLE)
        assert len(chunks) == 1


class TestSkipSections:
    def test_default_skip_sections_excluded(self) -> None:
        bioc = _wrap_bioc([
            _make_front_passage(),
            _make_passage("Good content.", section_type="INTRO"),
            _make_passage("References list.", section_type="REF"),
            _make_passage("Author contributions.", section_type="AUTH_CONT"),
            _make_passage("Supplementary data.", section_type="SUPPL"),
        ])
        chunks = chunk_bioc_document(bioc, doc_url=DOC_URL, doc_title=DOC_TITLE)
        sections = {c.doc_section for c in chunks}
        assert sections == {"INTRO"}

    def test_custom_skip_sections(self) -> None:
        bioc = _wrap_bioc([
            _make_front_passage(),
            _make_passage("Abstract.", section_type="ABSTRACT"),
            _make_passage("Intro.", section_type="INTRO"),
        ])
        chunks = chunk_bioc_document(
            bioc,
            doc_url=DOC_URL,
            doc_title=DOC_TITLE,
            skip_sections=frozenset({"ABSTRACT"}),
        )
        sections = {c.doc_section for c in chunks}
        assert "ABSTRACT" not in sections
        assert "INTRO" in sections

    def test_empty_skip_includes_all(self) -> None:
        bioc = _wrap_bioc([
            _make_front_passage(),
            _make_passage("Ref text.", section_type="REF"),
            _make_passage("Intro text.", section_type="INTRO"),
        ])
        chunks = chunk_bioc_document(
            bioc,
            doc_url=DOC_URL,
            doc_title=DOC_TITLE,
            skip_sections=frozenset(),
        )
        sections = {c.doc_section for c in chunks}
        assert "REF" in sections
        assert "INTRO" in sections

    def test_default_skip_set_values(self) -> None:
        assert DEFAULT_SKIP_SECTIONS == frozenset({"AUTH_CONT", "SUPPL", "REF", "COMP_INT"})


class TestOverlap:
    def test_consecutive_chunks_share_text(self) -> None:
        words_a = " ".join([f"alpha{i}" for i in range(200)])
        words_b = " ".join([f"beta{i}" for i in range(200)])
        bioc = _wrap_bioc([
            _make_front_passage(),
            _make_passage(words_a, section_type="INTRO"),
            _make_passage(words_b, section_type="INTRO"),
        ])
        chunks = chunk_bioc_document(
            bioc,
            doc_url=DOC_URL,
            doc_title=DOC_TITLE,
            chunk_tokens=150,
            overlap_tokens=30,
        )
        assert len(chunks) >= 2
        tail_of_first = chunks[0].text[-50:]
        assert tail_of_first[:20] in chunks[1].text

    def test_zero_overlap_no_shared_prefix(self) -> None:
        words_a = " ".join([f"alpha{i}" for i in range(200)])
        words_b = " ".join([f"beta{i}" for i in range(200)])
        bioc = _wrap_bioc([
            _make_front_passage(),
            _make_passage(words_a, section_type="INTRO"),
            _make_passage(words_b, section_type="INTRO"),
        ])
        chunks = chunk_bioc_document(
            bioc,
            doc_url=DOC_URL,
            doc_title=DOC_TITLE,
            chunk_tokens=150,
            overlap_tokens=0,
        )
        assert len(chunks) >= 2
        assert not chunks[1].text.startswith(chunks[0].text[:20])


class TestEmptyPassages:
    def test_empty_text_passages_skipped(self) -> None:
        bioc = _wrap_bioc([
            _make_front_passage(),
            _make_passage("", section_type="INTRO"),
            _make_passage("   ", section_type="INTRO"),
            _make_passage("Real content.", section_type="INTRO"),
        ])
        chunks = chunk_bioc_document(bioc, doc_url=DOC_URL, doc_title=DOC_TITLE)
        assert len(chunks) == 1
        assert "Real content." in chunks[0].text

    def test_all_empty_produces_no_chunks(self) -> None:
        bioc = _wrap_bioc([
            _make_front_passage(),
            _make_passage("", section_type="INTRO"),
        ])
        chunks = chunk_bioc_document(bioc, doc_url=DOC_URL, doc_title=DOC_TITLE)
        assert chunks == []


class TestMetadataExtraction:
    def test_extracts_all_fields(self) -> None:
        bioc = _wrap_bioc([_make_front_passage()])
        meta = extract_article_meta(bioc)
        assert isinstance(meta, BioCArticleMeta)
        assert meta.doi == "10.1234/test"
        assert meta.pmid == "98765"
        assert meta.pmc_id == "PMC12345"
        assert meta.year == "2025"
        assert meta.license == "CC BY"
        assert meta.authors == ["John Smith", "Jane Doe"]
        assert len(meta.keywords) == 3

    def test_missing_front_returns_empty_meta(self) -> None:
        bioc = _wrap_bioc([_make_passage("No front.", section_type="INTRO")])
        meta = extract_article_meta(bioc)
        assert meta.doi is None
        assert meta.authors == []
        assert meta.keywords == []

    def test_dict_input_accepted(self) -> None:
        """extract_article_meta accepts a bare collection dict, not just a list."""
        bioc_list = _wrap_bioc([_make_front_passage()])
        bioc_dict = bioc_list[0]
        meta = extract_article_meta(bioc_dict)
        assert meta.doi == "10.1234/test"


class TestHeadingPrefixing:
    def test_title_1_prepended_as_heading(self) -> None:
        bioc = _wrap_bioc([
            _make_front_passage(),
            _make_passage("Introduction", section_type="INTRO", ptype="title_1"),
            _make_passage("Body text.", section_type="INTRO"),
        ])
        chunks = chunk_bioc_document(bioc, doc_url=DOC_URL, doc_title=DOC_TITLE)
        assert len(chunks) >= 1
        assert "# Introduction" in chunks[0].text

    def test_title_2_prepended_as_heading(self) -> None:
        bioc = _wrap_bioc([
            _make_front_passage(),
            _make_passage("Subsection", section_type="METHODS", ptype="title_2"),
            _make_passage("Details.", section_type="METHODS"),
        ])
        chunks = chunk_bioc_document(bioc, doc_url=DOC_URL, doc_title=DOC_TITLE)
        assert "# Subsection" in chunks[0].text

    def test_abstract_title_prepended(self) -> None:
        bioc = _wrap_bioc([
            _make_front_passage(),
            _make_passage("ABSTRACT", section_type="ABSTRACT", ptype="abstract_title_1"),
            _make_passage("Abstract body.", section_type="ABSTRACT"),
        ])
        chunks = chunk_bioc_document(bioc, doc_url=DOC_URL, doc_title=DOC_TITLE)
        assert "# ABSTRACT" in chunks[0].text

    def test_table_caption_prefixed(self) -> None:
        bioc = _wrap_bioc([
            _make_front_passage(),
            _make_passage("Summary of results", section_type="RESULTS", ptype="table_caption"),
        ])
        chunks = chunk_bioc_document(bioc, doc_url=DOC_URL, doc_title=DOC_TITLE)
        assert "Table: Summary of results" in chunks[0].text

    def test_fig_caption_prefixed(self) -> None:
        bioc = _wrap_bioc([
            _make_front_passage(),
            _make_passage("Flow diagram", section_type="METHODS", ptype="fig_caption"),
        ])
        chunks = chunk_bioc_document(bioc, doc_url=DOC_URL, doc_title=DOC_TITLE)
        assert "Figure: Flow diagram" in chunks[0].text
