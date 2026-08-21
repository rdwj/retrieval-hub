"""Section-aware chunker for BioC JSON documents from PubMed Central."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

import tiktoken

from retrieval_hub.ingestion.chunking.token_fixed import Chunk

logger = logging.getLogger(__name__)

DEFAULT_SKIP_SECTIONS: frozenset[str] = frozenset({"AUTH_CONT", "SUPPL", "REF", "COMP_INT"})

_HEADING_TYPES = frozenset({"title_1", "title_2", "abstract_title_1"})
_CAPTION_PREFIXES: dict[str, str] = {
    "table_caption": "Table:",
    "fig_caption": "Figure:",
}


@dataclass
class BioCArticleMeta:
    """Article-level metadata extracted from BioC front passage."""

    doi: str | None = None
    pmid: str | None = None
    pmc_id: str | None = None
    keywords: list[str] = field(default_factory=list)
    authors: list[str] = field(default_factory=list)
    license: str | None = None
    year: str | None = None


def _get_document(bioc_data: list[Any] | dict[str, Any]) -> dict[str, Any]:
    """Navigate the BioC wrapper to the single BioCDocument."""
    if isinstance(bioc_data, list):
        collection = bioc_data[0]
    else:
        collection = bioc_data
    return collection["documents"][0]


def _format_passage_text(passage: dict[str, Any]) -> str:
    """Apply heading/caption prefixes to passage text."""
    text = passage.get("text", "").strip()
    if not text:
        return ""

    ptype = passage.get("infons", {}).get("type", "")
    if ptype in _HEADING_TYPES:
        return f"# {text}\n"
    prefix = _CAPTION_PREFIXES.get(ptype)
    if prefix:
        return f"{prefix} {text}"
    return text


def _extract_authors(infons: dict[str, Any]) -> list[str]:
    authors: list[str] = []
    i = 0
    while True:
        key = f"name_{i}"
        if key not in infons:
            break
        raw = infons[key]
        parts = dict(kv.split(":") for kv in raw.split(";") if ":" in kv)
        surname = parts.get("surname", "")
        given = parts.get("given-names", "")
        name = f"{given} {surname}".strip()
        if name:
            authors.append(name)
        i += 1
    return authors


def extract_article_meta(bioc_data: list[Any] | dict[str, Any]) -> BioCArticleMeta:
    """Extract article metadata from the BioC front passage."""
    doc = _get_document(bioc_data)
    for passage in doc.get("passages", []):
        if passage.get("infons", {}).get("type") == "front":
            infons = passage["infons"]
            kwd_raw = infons.get("kwd", "")
            keywords = [k.strip() for k in kwd_raw.split() if k.strip()] if kwd_raw else []
            return BioCArticleMeta(
                doi=infons.get("article-id_doi"),
                pmid=infons.get("article-id_pmid"),
                pmc_id=infons.get("article-id_pmc"),
                keywords=keywords,
                authors=_extract_authors(infons),
                license=infons.get("license"),
                year=infons.get("year"),
            )
    return BioCArticleMeta()


def _content_passages(
    doc: dict[str, Any],
    skip_sections: frozenset[str],
) -> list[dict[str, Any]]:
    """Filter passages to content-bearing ones, skipping front, ref, and user-specified sections."""
    result: list[dict[str, Any]] = []
    for p in doc.get("passages", []):
        infons = p.get("infons", {})
        if infons.get("type") == "front":
            continue
        section_type = infons.get("section_type", "")
        if section_type in skip_sections:
            continue
        text = p.get("text", "").strip()
        if not text:
            continue
        result.append(p)
    return result


def _token_count(text: str, encoding: tiktoken.Encoding) -> int:
    return len(encoding.encode(text))


def chunk_bioc_document(
    bioc_data: list[Any] | dict[str, Any],
    *,
    doc_url: str,
    doc_title: str,
    chunk_tokens: int = 512,
    overlap_tokens: int = 0,
    encoding_name: str = "cl100k_base",
    respect_section_boundaries: bool = True,
    skip_sections: frozenset[str] | None = None,
) -> list[Chunk]:
    """Chunk a BioC JSON document into section-aware chunks.

    Passages are natural semantic units and are never split mid-passage.
    When ``respect_section_boundaries`` is True (the default), a new chunk
    starts at every section boundary even if the previous chunk has room.
    """
    if skip_sections is None:
        skip_sections = DEFAULT_SKIP_SECTIONS

    doc = _get_document(bioc_data)
    passages = _content_passages(doc, skip_sections)

    if not passages:
        logger.info("chunk.bioc url=%s no_passages", doc_url)
        return []

    encoding = tiktoken.get_encoding(encoding_name)

    formatted: list[tuple[str, str]] = []
    for p in passages:
        text = _format_passage_text(p)
        if not text:
            continue
        section_type = p.get("infons", {}).get("section_type", "")
        formatted.append((section_type, text))

    chunks: list[Chunk] = []
    current_texts: list[str] = []
    current_tokens = 0
    current_section: str | None = None
    overlap_text = ""

    def _finalize_chunk() -> None:
        nonlocal overlap_text
        if not current_texts:
            return
        joined = "\n".join(current_texts)
        tok_count = _token_count(joined, encoding)
        chunks.append(
            Chunk(
                text=joined,
                token_count=tok_count,
                chunk_index=len(chunks),
                doc_url=doc_url,
                doc_title=doc_title,
                doc_section=current_section,
            )
        )
        if overlap_tokens > 0:
            tokens = encoding.encode(joined)
            tail = tokens[-overlap_tokens:]
            overlap_text = encoding.decode(tail)
        else:
            overlap_text = ""

    for section_type, text in formatted:
        passage_tokens = _token_count(text, encoding)
        section_changed = section_type != current_section

        if respect_section_boundaries and section_changed and current_texts:
            _finalize_chunk()
            current_texts = []
            current_tokens = 0
            if overlap_text:
                current_texts.append(overlap_text)
                current_tokens = _token_count(overlap_text, encoding)

        if current_section is None or section_changed:
            current_section = section_type

        would_exceed = current_tokens + passage_tokens > chunk_tokens and current_texts

        if would_exceed:
            _finalize_chunk()
            current_texts = []
            current_tokens = 0
            current_section = section_type
            if overlap_text:
                current_texts.append(overlap_text)
                current_tokens = _token_count(overlap_text, encoding)

        current_texts.append(text)
        current_tokens += passage_tokens

    _finalize_chunk()

    logger.info(
        "chunk.bioc url=%s chunks=%d passages=%d",
        doc_url,
        len(chunks),
        len(passages),
    )
    return chunks
