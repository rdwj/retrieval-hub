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
    from retrieval_hub.retrieval.api import RefineOutput, RetrievalResult


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
        doc_section: list[str] | None = None,
        scope_entity_id: str | None = None,
    ) -> list[RetrievalResult]:
        """Return top-k normalized results for ``query_text``.

        Implementations must populate every lineage field on each
        ``RetrievalResult`` (``physical_index_id``, ``recipe_version``,
        ``request_id``) so the MCP layer never has to reconstruct them.

        Parameters
        ----------
        doc_section:
            Optional list of section names to restrict the search to.
            When provided, only chunks whose ``doc_section`` column
            matches one of the given values are considered.  For graph
            sources this corresponds to entity types (e.g., "Patient",
            "Condition"); for document sources it is section header text.
        scope_entity_id:
            Restrict retrieval to a specific subgraph by providing a
            seed entity ID.  The system traverses the graph from this
            entity to find all connected entities, then restricts the
            vector search to those entities.  Only supported for
            graph-family sources.
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
        strategy: str = "adjacent",
        max_context_tokens: int | None = None,
    ) -> RefineOutput:
        """Return additional context around a previously retrieved chunk."""
