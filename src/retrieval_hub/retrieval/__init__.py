"""High-level retrieval API for the core library.

This subpackage contains the entry point a caller uses to retrieve top-k hits
for a query against a named source. It loads the source from the catalog,
resolves the active physical index, dispatches to the correct source adapter
based on the source's family, and returns normalized ``RetrievalResult``
items carrying the lineage handle described in ``docs/catalog.md``.
"""

from __future__ import annotations

from retrieval_hub.retrieval.api import RetrievalResult, query

__all__ = ["RetrievalResult", "query"]
