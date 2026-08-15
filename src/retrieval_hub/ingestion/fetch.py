"""Stage 1 of the ingestion pipeline: fetch raw bytes from an origin.

Step 4 implements the ``web_crawl``-like origin in its simplest form: a
single-URL HTTP GET. That's enough for the initial hand-run against the
Red Hat AI docs single-HTML target. Fallback loading from a local directory
is also provided so ingestion still runs when the network is unavailable.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

import httpx

logger = logging.getLogger(__name__)


DEFAULT_TIMEOUT_SECONDS = 60.0
DEFAULT_USER_AGENT = (
    "retrieval-hub-ingest/0.0.1 (+https://github.com/redhat-ai-americas/retrieval-hub)"
)


class FetchError(RuntimeError):
    """Raised when a fetch stage fails in a non-recoverable way."""


@dataclass
class FetchedDocument:
    """One raw document fetched from an origin.

    ``content`` is the decoded body when the origin yields text (HTML,
    Markdown). For binary origins (PDF) callers should use ``raw_bytes``.
    """

    url: str
    title: str
    content: str
    content_type: str
    raw_bytes: bytes = b""
    metadata: dict[str, str] = field(default_factory=dict)


def fetch_html_url(
    url: str,
    *,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
    user_agent: str = DEFAULT_USER_AGENT,
) -> FetchedDocument:
    """Fetch a single HTML document over HTTP.

    Raises ``FetchError`` on non-2xx responses, transport errors, or rate
    limiting. Callers are expected to catch and fall back to their own
    strategy if appropriate.
    """
    logger.info("fetch.fetch_html_url url=%s", url)
    headers = {"User-Agent": user_agent, "Accept": "text/html,*/*"}
    try:
        with httpx.Client(
            timeout=timeout, follow_redirects=True, headers=headers
        ) as client:
            response = client.get(url)
    except httpx.HTTPError as exc:
        raise FetchError(f"HTTP error fetching {url}: {exc}") from exc

    if response.status_code >= 400:
        raise FetchError(
            f"Non-2xx response fetching {url}: {response.status_code} {response.reason_phrase}"
        )

    content_type = response.headers.get("content-type", "text/html")
    return FetchedDocument(
        url=url,
        title=url,
        content=response.text,
        content_type=content_type,
        raw_bytes=response.content,
        metadata={"status_code": str(response.status_code)},
    )


def fetch_pdf_url(
    url: str,
    *,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
    user_agent: str = DEFAULT_USER_AGENT,
) -> FetchedDocument:
    """Fetch a single PDF document over HTTP, returning raw bytes."""
    logger.info("fetch.fetch_pdf_url url=%s", url)
    headers = {"User-Agent": user_agent, "Accept": "application/pdf,*/*"}
    try:
        with httpx.Client(
            timeout=timeout, follow_redirects=True, headers=headers
        ) as client:
            response = client.get(url)
    except httpx.HTTPError as exc:
        raise FetchError(f"HTTP error fetching {url}: {exc}") from exc

    if response.status_code >= 400:
        raise FetchError(
            f"Non-2xx response fetching {url}: {response.status_code} {response.reason_phrase}"
        )

    content_type = response.headers.get("content-type", "application/pdf")
    return FetchedDocument(
        url=url,
        title=url,
        content="",
        content_type=content_type,
        raw_bytes=response.content,
        metadata={"status_code": str(response.status_code)},
    )


# File stems that are conventionally documentation-about-the-directory
# rather than corpus content, and should be skipped when loading a
# fallback corpus. Case-insensitive comparison against `Path.stem`.
_FALLBACK_CORPUS_SKIP_STEMS = frozenset({"readme", "index", "license", "contributing"})

# Alias used by both flat and recursive loaders.
_SKIP_STEMS = _FALLBACK_CORPUS_SKIP_STEMS


def load_fallback_corpus(corpus_dir: Path) -> list[FetchedDocument]:
    """Load a directory of hand-written Markdown files as a fallback corpus.

    Used when real network fetches fail (rate limiting, offline, etc.). Each
    ``.md`` file in the directory becomes a ``FetchedDocument`` whose URL is
    a synthetic ``file://`` identifier and whose title is the file stem.

    Meta-files like ``README.md`` are skipped — they're about the corpus,
    not content of the corpus. The skip list is in
    ``_FALLBACK_CORPUS_SKIP_STEMS``.
    """
    corpus_dir = Path(corpus_dir)
    if not corpus_dir.is_dir():
        raise FetchError(f"Fallback corpus directory does not exist: {corpus_dir}")

    docs: list[FetchedDocument] = []
    skipped: list[str] = []
    for md_path in sorted(corpus_dir.glob("*.md")):
        if md_path.stem.lower() in _FALLBACK_CORPUS_SKIP_STEMS:
            skipped.append(md_path.name)
            continue
        text = md_path.read_text(encoding="utf-8")
        docs.append(
            FetchedDocument(
                url=f"file://{md_path.resolve()}",
                title=md_path.stem.replace("-", " ").title(),
                content=text,
                content_type="text/markdown",
                raw_bytes=text.encode("utf-8"),
                metadata={"source": "fallback"},
            )
        )
    logger.info(
        "fetch.load_fallback_corpus dir=%s count=%d skipped=%s",
        corpus_dir,
        len(docs),
        skipped,
    )
    return docs


def load_corpus_tree(
    corpus_dir: Path,
    *,
    url_map: dict[str, str] | None = None,
) -> list[FetchedDocument]:
    """Recursively walk *corpus_dir* loading every ``.md`` file.

    Unlike :func:`load_fallback_corpus`, this function descends into
    subdirectories and derives document titles from the directory structure
    (``category/slug/doc-type``).

    When *url_map* is provided, each document's URL is resolved by
    looking up ``"{slug}/{document_type}"`` (e.g.
    ``"hypertension/full-guideline"``) in the map.  Documents not found
    in the map fall back to a ``file://`` URL.
    """
    corpus_dir = Path(corpus_dir)
    if not corpus_dir.is_dir():
        raise FetchError(f"Corpus directory does not exist: {corpus_dir}")

    docs: list[FetchedDocument] = []
    skipped: list[str] = []

    for md_path in corpus_dir.rglob("*.md"):
        if md_path.stem.lower() in _SKIP_STEMS:
            skipped.append(str(md_path.relative_to(corpus_dir)))
            continue

        relative = md_path.relative_to(corpus_dir)
        parts = relative.parent.parts
        title = "/".join(parts) + "/" + relative.stem if parts else relative.stem

        metadata: dict[str, str] = {"source": "corpus_tree"}
        if len(parts) >= 1:
            metadata["category"] = parts[0]
        if len(parts) >= 2:
            metadata["slug"] = parts[1]
        metadata["document_type"] = relative.stem

        doc_url = f"file://{md_path.resolve()}"
        if url_map and len(parts) >= 2:
            map_key = f"{parts[1]}/{relative.stem}"
            doc_url = url_map.get(map_key, doc_url)

        text = md_path.read_text(encoding="utf-8")
        docs.append(
            FetchedDocument(
                url=doc_url,
                title=title,
                content=text,
                content_type="text/markdown",
                raw_bytes=text.encode("utf-8"),
                metadata=metadata,
            )
        )

    docs.sort(key=lambda d: d.title)
    logger.info(
        "fetch.load_corpus_tree dir=%s count=%d skipped=%s",
        corpus_dir,
        len(docs),
        skipped,
    )
    return docs
