"""Stage 3 of the ingestion pipeline: normalize parsed output.

For step 4 normalization is deliberately light:

- Strip common boilerplate lines (cookie banners, "Skip to main content",
  "On this page", empty link text lines, deeply-indented nav artifacts).
- Collapse runs of blank lines.
- Trim leading/trailing whitespace.
- Drop the document entirely if the remaining body is shorter than a
  small threshold (keeps 404 pages, login walls etc. out of the index).

These are heuristics tuned against docs.redhat.com single-html pages; they
work fine for the fallback corpus too since the fallback is hand-written
and already clean.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field

from retrieval_hub.ingestion.parse import ParsedDocument, ParsedSection

logger = logging.getLogger(__name__)


MIN_BODY_CHARS = 200


@dataclass
class NormalizedDocument:
    """Output of stage 3. Ready to be chunked."""

    url: str
    title: str
    text: str
    sections: list[ParsedSection] = field(default_factory=list)
    metadata: dict[str, str] = field(default_factory=dict)


# Boilerplate patterns. Each is a compiled regex applied to the full text
# after parsing; matched substrings are removed.
_BOILERPLATE_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"(?im)^skip to main content.*$"),
    re.compile(r"(?im)^skip to content.*$"),
    re.compile(r"(?im)^on this page.*$"),
    re.compile(r"(?im)^jump to section.*$"),
    re.compile(r"(?im)^table of contents.*$"),
    re.compile(r"(?im)^back to top.*$"),
    re.compile(r"(?im)^cookie preferences.*$"),
    re.compile(r"(?im)^we use cookies.*$"),
    re.compile(r"(?im)^accept all cookies.*$"),
    re.compile(r"(?im)^© \d{4} red hat.*$"),
    re.compile(r"(?im)^all rights reserved.*$"),
    re.compile(r"(?im)^privacy statement.*$"),
    re.compile(r"(?im)^terms of use.*$"),
    re.compile(r"(?im)^print this.*$"),
    re.compile(r"(?im)^was this helpful.*$"),
    re.compile(r"(?im)^edit this page.*$"),
]


_BLANKS_RE = re.compile(r"\n{3,}")


def normalize_document(parsed: ParsedDocument) -> NormalizedDocument | None:
    """Strip boilerplate and collapse blank lines. Returns None if the body is too short."""
    text = parsed.text or ""

    for pattern in _BOILERPLATE_PATTERNS:
        text = pattern.sub("", text)

    # Collapse lots of blank lines and trim.
    text = _BLANKS_RE.sub("\n\n", text).strip()

    if len(text) < MIN_BODY_CHARS:
        logger.info(
            "normalize.normalize_document url=%s dropped short=%d", parsed.url, len(text)
        )
        return None

    return NormalizedDocument(
        url=parsed.url,
        title=parsed.title,
        text=text,
        sections=list(parsed.sections),
        metadata={**parsed.metadata, "normalized": "true"},
    )


def find_section_for_offset(
    sections: list[ParsedSection], offset: int
) -> str | None:
    """Return the most recent section heading preceding ``offset``, if any."""
    current: str | None = None
    for section in sections:
        if section.char_offset <= offset:
            current = section.heading
        else:
            break
    return current
