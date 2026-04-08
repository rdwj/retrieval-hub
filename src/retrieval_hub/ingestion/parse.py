"""Stage 2 of the ingestion pipeline: parse raw bytes into structured text.

Per ``docs/ingestion.md`` the ``document`` family parser is Docling. Step 4
tries Docling first for real HTML/PDF parsing and falls back to a BS4 +
markdownify path if Docling is unavailable or crashes. The fallback exists
because Docling can be heavy on Mac ARM64 and the ingestion script should
stay runnable even when Docling's environment is unhappy.

The output type is ``ParsedDocument`` — title, plain text (markdown-ish),
and a flat list of section headings with their offsets in the text.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field

from retrieval_hub.ingestion.fetch import FetchedDocument

logger = logging.getLogger(__name__)


@dataclass
class ParsedSection:
    """One heading / section within a parsed document."""

    heading: str
    level: int
    char_offset: int


@dataclass
class ParsedDocument:
    """Output of stage 2. A normalized intermediate representation."""

    url: str
    title: str
    text: str
    content_type: str
    sections: list[ParsedSection] = field(default_factory=list)
    metadata: dict[str, str] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def parse_document(doc: FetchedDocument) -> ParsedDocument:
    """Parse a fetched document based on its content type.

    - HTML goes through Docling when available, otherwise BS4 + markdownify.
    - PDFs go through Docling when available, otherwise pypdf.
    - Markdown is passed through as-is (with a light section scan).
    """
    ct = (doc.content_type or "").lower()
    if "html" in ct:
        return _parse_html(doc)
    if "pdf" in ct:
        return _parse_pdf(doc)
    if "markdown" in ct or ct in ("text/plain", ""):
        return _parse_markdown(doc)
    logger.warning(
        "parse.parse_document unknown content_type=%s; treating as markdown", ct
    )
    return _parse_markdown(doc)


# ---------------------------------------------------------------------------
# HTML
# ---------------------------------------------------------------------------


def _parse_html(doc: FetchedDocument) -> ParsedDocument:
    """Parse an HTML document with Docling first and BS4 as fallback."""
    try:
        return _parse_html_with_docling(doc)
    except Exception as exc:  # pragma: no cover - fallback path
        logger.warning(
            "parse._parse_html_with_docling failed url=%s error=%r; "
            "falling back to BS4+markdownify",
            doc.url,
            exc,
        )
        return _parse_html_with_bs4(doc)


def _parse_html_with_docling(doc: FetchedDocument) -> ParsedDocument:
    """Parse HTML with Docling. Raises on any failure so the caller can fall back."""
    from docling.datamodel.base_models import DocumentStream
    from docling.document_converter import DocumentConverter

    stream = DocumentStream(
        name="fetched.html",
        stream=_bytes_stream(doc.raw_bytes or doc.content.encode("utf-8")),
    )
    converter = DocumentConverter()
    result = converter.convert(stream)
    docling_doc = result.document
    markdown = docling_doc.export_to_markdown()
    title = _extract_title_from_markdown(markdown) or doc.title
    sections = _extract_markdown_sections(markdown)

    return ParsedDocument(
        url=doc.url,
        title=title,
        text=markdown,
        content_type=doc.content_type,
        sections=sections,
        metadata={**doc.metadata, "parser": "docling"},
    )


def _parse_html_with_bs4(doc: FetchedDocument) -> ParsedDocument:
    """Fallback HTML parser using BeautifulSoup + markdownify."""
    from bs4 import BeautifulSoup
    from markdownify import markdownify

    soup = BeautifulSoup(
        doc.content or (doc.raw_bytes or b"").decode("utf-8", errors="replace"),
        "html.parser",
    )

    # Strip clearly non-content elements before conversion.
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()

    title = (soup.title.string.strip() if soup.title and soup.title.string else doc.title)

    main = soup.find("main") or soup.find("article") or soup.body or soup
    html_fragment = str(main)
    markdown = markdownify(html_fragment, heading_style="ATX")

    sections = _extract_markdown_sections(markdown)
    return ParsedDocument(
        url=doc.url,
        title=title or doc.title,
        text=markdown,
        content_type=doc.content_type,
        sections=sections,
        metadata={**doc.metadata, "parser": "bs4"},
    )


# ---------------------------------------------------------------------------
# PDF
# ---------------------------------------------------------------------------


def _parse_pdf(doc: FetchedDocument) -> ParsedDocument:
    """Parse a PDF with Docling first and pypdf as fallback."""
    try:
        return _parse_pdf_with_docling(doc)
    except Exception as exc:  # pragma: no cover - fallback path
        logger.warning(
            "parse._parse_pdf_with_docling failed url=%s error=%r; "
            "falling back to pypdf",
            doc.url,
            exc,
        )
        return _parse_pdf_with_pypdf(doc)


def _parse_pdf_with_docling(doc: FetchedDocument) -> ParsedDocument:
    from docling.datamodel.base_models import DocumentStream
    from docling.document_converter import DocumentConverter

    stream = DocumentStream(
        name="fetched.pdf",
        stream=_bytes_stream(doc.raw_bytes),
    )
    converter = DocumentConverter()
    result = converter.convert(stream)
    markdown = result.document.export_to_markdown()
    title = _extract_title_from_markdown(markdown) or doc.title
    sections = _extract_markdown_sections(markdown)

    return ParsedDocument(
        url=doc.url,
        title=title,
        text=markdown,
        content_type=doc.content_type,
        sections=sections,
        metadata={**doc.metadata, "parser": "docling"},
    )


def _parse_pdf_with_pypdf(doc: FetchedDocument) -> ParsedDocument:
    import io

    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(doc.raw_bytes))
    pages = [page.extract_text() or "" for page in reader.pages]
    text = "\n\n".join(pages)
    return ParsedDocument(
        url=doc.url,
        title=doc.title,
        text=text,
        content_type=doc.content_type,
        sections=[],
        metadata={**doc.metadata, "parser": "pypdf"},
    )


# ---------------------------------------------------------------------------
# Markdown
# ---------------------------------------------------------------------------


def _parse_markdown(doc: FetchedDocument) -> ParsedDocument:
    text = doc.content or (doc.raw_bytes or b"").decode("utf-8", errors="replace")
    title = _extract_title_from_markdown(text) or doc.title
    sections = _extract_markdown_sections(text)
    return ParsedDocument(
        url=doc.url,
        title=title,
        text=text,
        content_type=doc.content_type or "text/markdown",
        sections=sections,
        metadata={**doc.metadata, "parser": "passthrough_markdown"},
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$", re.MULTILINE)


def _extract_title_from_markdown(md: str) -> str | None:
    """Return the first ``#`` heading in the text, if any."""
    for match in _HEADING_RE.finditer(md):
        level = len(match.group(1))
        if level == 1:
            return match.group(2).strip()
    # Fall back to the first heading at any level.
    fallback_match = _HEADING_RE.search(md)
    if fallback_match:
        return fallback_match.group(2).strip()
    return None


def _extract_markdown_sections(md: str) -> list[ParsedSection]:
    """Return every markdown heading with its char offset."""
    sections: list[ParsedSection] = []
    for match in _HEADING_RE.finditer(md):
        sections.append(
            ParsedSection(
                heading=match.group(2).strip(),
                level=len(match.group(1)),
                char_offset=match.start(),
            )
        )
    return sections


def _bytes_stream(data: bytes) -> object:
    """Return a BytesIO-wrapped stream for Docling APIs that want one."""
    import io

    return io.BytesIO(data)
