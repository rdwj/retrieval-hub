"""Source-family adapters.

Per ``docs/catalog.md`` the family of a source is a hard discriminator that
selects the adapter used at retrieval time. Step 4 ships the first real
adapter, ``DocumentAdapter``, and the abstract ``SourceAdapter`` base every
future family adapter will implement.
"""

from __future__ import annotations

from retrieval_hub.adapters.base import SourceAdapter
from retrieval_hub.adapters.document import DocumentAdapter
from retrieval_hub.adapters.process import ProcessAdapter

__all__ = ["DocumentAdapter", "ProcessAdapter", "SourceAdapter"]
