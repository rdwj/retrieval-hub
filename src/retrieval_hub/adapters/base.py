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

    def _expand_doc_section(
        self, doc_section: list[str] | None,
    ) -> list[str] | None:
        """Expand doc_section values using semantic_context entity aliases.

        If the source has a semantic_context with entity definitions, checks
        each requested doc_section value against entity aliases. When a value
        matches an alias, the entity's canonical name (which matches the
        doc_section column) is added to the filter list.
        """
        if not doc_section:
            return doc_section
        sc = getattr(self.source, "semantic_context", None)
        if not sc or not isinstance(sc, dict):
            return doc_section
        entities = sc.get("entities") or []
        if not entities:
            return doc_section

        expanded = set(doc_section)
        for val in doc_section:
            val_lower = val.lower()
            for ent in entities:
                name = ent.get("name", "")
                aliases = ent.get("aliases") or []
                if val_lower == name.lower():
                    continue
                if any(a.lower() == val_lower for a in aliases):
                    expanded.add(name)
        return list(expanded) if expanded != set(doc_section) else doc_section

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
