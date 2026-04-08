"""Source-level access policy.

This is the catalog-side enforcement described in ``docs/auth.md`` under
"Source-level access control". The auth service does not know about sources;
it only issues identity claims. This module is the only place that decides
whether a given identity may take a given action against a given source.

Round-1 rules (from ``docs/auth.md``):

- ``Draft`` sources are not visible to agents at all (only to owner /
  maintainers / admins on the human-facing surface).
- ``Retired`` sources are not visible to agents either; existing retrieval
  calls return a structured error.
- ``public`` visibility means anyone authenticated may ``list`` / ``read`` /
  ``query`` / ``rewrite``.
- ``restricted`` visibility means the identity's groups must intersect the
  source's ``allowed_groups`` (or the identity must be a human admin).
"""

from __future__ import annotations

from typing import Literal

from retrieval_hub.models.enums import AccessVisibility, SourceStatus
from retrieval_hub.models.identity import Identity
from retrieval_hub.models.source import Source

Action = Literal["list", "read", "query", "rewrite"]

_AGENT_VISIBLE_STATUSES: frozenset[SourceStatus] = frozenset(
    {SourceStatus.CURATED, SourceStatus.PUBLISHED}
)
_AGENT_KINDS: frozenset[str] = frozenset({"agent", "service", "client"})


def _is_admin_user(identity: Identity) -> bool:
    """Return True if ``identity`` is a human user with the ``admin`` group."""
    return identity.kind == "user" and "admin" in identity.groups


def _allowed_groups(source: Source) -> list[str]:
    """Extract ``access.allowed_groups`` from a source row, defaulting to []."""
    access = source.access or {}
    groups = access.get("allowed_groups") or []
    if not isinstance(groups, list):
        return []
    return [str(g) for g in groups]


def _visibility(source: Source) -> AccessVisibility:
    """Return the effective visibility for a source row.

    Falls back to the source's ``visibility`` column if the JSON ``access``
    blob does not pin its own value (which is the common case in v0).
    """
    access = source.access or {}
    raw = access.get("visibility")
    if isinstance(raw, str):
        try:
            return AccessVisibility(raw)
        except ValueError:
            pass
    return source.visibility


def can_access(identity: Identity, source: Source, action: Action) -> bool:
    """Return True if ``identity`` may perform ``action`` on ``source``.

    The contract follows the pseudocode in ``docs/auth.md`` exactly. Action
    enumeration is the round-1 set: ``list`` / ``read`` / ``query`` /
    ``rewrite``.

    Notes on lifecycle interaction:

    - Drafts are owner-only and therefore not agent-visible. The catalog UI
      bypasses this check entirely for owner / admin views; agents always
      go through this function and so always see drafts as inaccessible.
    - Retired sources are likewise not agent-visible. Callers should
      translate that into a structured "retired" error so agents can handle
      it gracefully.
    - Admin humans bypass restricted-visibility checks (only).
    """
    # Lifecycle gate: agents only see Curated/Published sources.
    if identity.kind in _AGENT_KINDS and source.status not in _AGENT_VISIBLE_STATUSES:
        return False

    visibility = _visibility(source)

    if visibility == AccessVisibility.PUBLIC:
        return action in {"list", "read", "query", "rewrite"}

    if visibility == AccessVisibility.RESTRICTED:
        if _is_admin_user(identity):
            return True
        allowed = set(_allowed_groups(source))
        if not allowed:
            return False
        return any(g in allowed for g in identity.groups)

    return False
