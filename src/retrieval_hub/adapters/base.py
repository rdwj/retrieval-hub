"""Abstract base class for source-family adapters.

An adapter knows how to take a query and the catalog record of a source
(specifically the active physical index and the recipe version it was built
with) and produce ``RetrievalResult`` items. Each family ships its own
subclass; the query API picks the right one based on ``Source.family``.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

from retrieval_hub.models import PhysicalIndex, RecipeVersion, Source

if TYPE_CHECKING:
    from retrieval_hub.retrieval.api import RetrievalResult


class SourceAdapter(ABC):
    """Base class every source-family adapter extends."""

    def __init__(
        self,
        *,
        source: Source,
        physical_index: PhysicalIndex,
        recipe_version: RecipeVersion,
    ) -> None:
        self.source = source
        self.physical_index = physical_index
        self.recipe_version = recipe_version

    @abstractmethod
    def retrieve(
        self,
        query_text: str,
        *,
        top_k: int,
        request_id: str,
    ) -> list[RetrievalResult]:
        """Return top-k normalized results for ``query_text``.

        Implementations must populate every lineage field on each
        ``RetrievalResult`` (``physical_index_id``, ``recipe_version``,
        ``request_id``) so the MCP layer never has to reconstruct them.
        """

    @abstractmethod
    def refine(
        self,
        *,
        doc_title: str,
        chunk_index: int,
        query: str,
        window: int,
        request_id: str,
    ) -> list[RetrievalResult]:
        """Return additional context around a previously retrieved chunk."""
