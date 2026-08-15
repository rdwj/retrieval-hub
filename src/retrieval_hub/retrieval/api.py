"""High-level retrieval entry point and normalized result shape.

``RetrievalResult`` is the normalized per-hit shape every adapter must return.
It carries the minimum information the MCP layer (future step 5) needs to
render a hit plus the lineage handle (``physical_index_id``, ``recipe_version``,
``request_id``) per ``docs/catalog.md`` and ``docs/mcp-server.md``.

``query`` is the one-shot entry point the hand-run query script uses. It
mirrors what a future MCP tool would do: look up the source by slug, resolve
its active physical index, build an adapter of the correct family, and run
the retrieve call.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass

from sqlalchemy.orm import Session

from retrieval_hub.adapters.base import SourceAdapter
from retrieval_hub.adapters.document import DocumentAdapter
from retrieval_hub.models import PhysicalIndex, RecipeVersion, Source
from retrieval_hub.models.enums import SourceFamily

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class RetrievalResult:
    """Normalized per-hit result returned by every adapter.

    ``physical_index_id``, ``recipe_version`` and ``request_id`` form the
    lineage handle callers need to answer "where did this result come from?"
    without reading adapter internals.
    """

    text: str
    score: float
    doc_title: str
    doc_url: str
    doc_section: str | None
    physical_index_id: str
    recipe_version: int
    request_id: str


class SourceNotFoundError(LookupError):
    """Raised when ``query`` cannot find a source by slug."""


class SourceNotQueryableError(RuntimeError):
    """Raised when the source exists but has no active physical index."""


class UnsupportedFamilyError(RuntimeError):
    """Raised when no adapter exists for the source's family yet."""


def _build_adapter(
    source: Source,
    physical_index: PhysicalIndex,
    recipe_version: RecipeVersion,
    *,
    vectors_db_url: str | None,
) -> SourceAdapter:
    """Return the right adapter instance for the source's family."""
    if source.family in (
        SourceFamily.DOCUMENT,
        SourceFamily.CLINICAL_DOCUMENT,
        SourceFamily.CODE,
    ):
        return DocumentAdapter(
            source=source,
            physical_index=physical_index,
            recipe_version=recipe_version,
            vectors_db_url=vectors_db_url,
        )
    raise UnsupportedFamilyError(
        f"No adapter implementation for family {source.family!r} yet. "
        f"Supported families: document, clinical_document, code."
    )


def query(
    source_slug: str,
    query_text: str,
    *,
    session: Session,
    top_k: int = 10,
    vectors_db_url: str | None = None,
    request_id: str | None = None,
) -> list[RetrievalResult]:
    """Return top-k retrieval results for ``query_text`` against a source.

    Parameters
    ----------
    source_slug:
        The catalog slug of the source to query.
    query_text:
        The raw user query.
    session:
        A live SQLAlchemy session against the catalog database.
    top_k:
        How many hits to return. Defaults to 10.
    vectors_db_url:
        Optional override for the vectors-database connection URL. If absent,
        the document adapter will pull from the ``RETRIEVAL_HUB_VECTORS_DB_URL``
        environment variable.
    request_id:
        Optional caller-provided request id. One is generated if absent so
        every result carries a stable lineage handle.

    Raises
    ------
    SourceNotFoundError
        If no source exists with the given slug.
    SourceNotQueryableError
        If the source exists but has no active physical index.
    UnsupportedFamilyError
        If the source's family has no registered adapter.
    """
    source = session.query(Source).filter(Source.slug == source_slug).one_or_none()
    if source is None:
        raise SourceNotFoundError(f"No source with slug {source_slug!r}")

    if source.active_physical_index_id is None:
        raise SourceNotQueryableError(
            f"Source {source_slug!r} has no active physical index; "
            f"run ingestion before querying it."
        )

    physical_index = (
        session.query(PhysicalIndex)
        .filter(PhysicalIndex.id == source.active_physical_index_id)
        .one()
    )
    recipe_version = (
        session.query(RecipeVersion)
        .filter(RecipeVersion.id == physical_index.recipe_version_id)
        .one()
    )

    adapter = _build_adapter(
        source,
        physical_index,
        recipe_version,
        vectors_db_url=vectors_db_url,
    )

    effective_request_id = request_id or str(uuid.uuid4())
    logger.info(
        "retrieval.query source=%s top_k=%d request_id=%s",
        source_slug,
        top_k,
        effective_request_id,
    )

    return adapter.retrieve(
        query_text,
        top_k=top_k,
        request_id=effective_request_id,
    )
