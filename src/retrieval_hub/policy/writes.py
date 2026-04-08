"""Source-level write policy.

Per ``docs/catalog.md`` and ``docs/auth.md``, agent writes are governed by
**two gates** that must both pass:

1. The caller must hold the ``sources.write`` scope (or whatever scope the
   source has elected via ``agent_write_policy.scope_required``).
2. The source must have ``agent_write_policy.allowed = true`` and the
   requested write mode must be in ``agent_write_policy.write_modes``, and
   the caller's identity groups must intersect ``allowed_groups`` (or
   ``allowed_groups`` must be empty, meaning "anyone with the scope").

Default for any source whose owner has not explicitly set a write policy is
**deny**, matching catalog.md's "default false on most curated sources" rule.
"""

from __future__ import annotations

from typing import Any

from retrieval_hub.models.enums import SourceStatus, WriteMode
from retrieval_hub.models.identity import Identity
from retrieval_hub.models.source import Source

DEFAULT_WRITE_SCOPE = "sources.write"


def _policy(source: Source) -> dict[str, Any]:
    """Return the source's agent_write_policy as a dict (may be empty)."""
    policy = source.agent_write_policy
    return policy if isinstance(policy, dict) else {}


def can_write(identity: Identity, source: Source, write_mode: WriteMode) -> bool:
    """Return True if ``identity`` may perform ``write_mode`` against ``source``.

    Returns False unless every gate from ``docs/catalog.md`` is satisfied.
    """
    # Lifecycle gate: writes are only allowed against active sources.
    if source.status not in {SourceStatus.CURATED, SourceStatus.PUBLISHED}:
        return False

    policy = _policy(source)
    if not policy.get("allowed", False):
        return False

    required_scope = policy.get("scope_required") or DEFAULT_WRITE_SCOPE
    if not identity.has_scope(str(required_scope)):
        return False

    allowed_modes_raw = policy.get("write_modes") or []
    allowed_modes: set[str] = {str(m) for m in allowed_modes_raw}
    if write_mode.value not in allowed_modes:
        return False

    allowed_groups_raw = policy.get("allowed_groups") or []
    allowed_groups: set[str] = {str(g) for g in allowed_groups_raw}
    if allowed_groups and not any(g in allowed_groups for g in identity.groups):
        return False

    return True
