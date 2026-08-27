"""Identity extraction from FastMCP access tokens.

Converts FastMCP's ``AccessToken`` (populated by ``JWTVerifier`` middleware)
into the core library's ``Identity`` dataclass so the policy module can
make access decisions.
"""

from __future__ import annotations

import logging

from fastmcp.server.dependencies import get_access_token

from retrieval_hub.models.identity import Identity

logger = logging.getLogger(__name__)


def get_current_identity() -> Identity | None:
    """Build an ``Identity`` from the current request's access token.

    Returns ``None`` when auth is disabled (no JWKS URI configured),
    which lets callers skip policy checks for backward compatibility.
    """
    token = get_access_token()
    if token is None:
        return None

    claims = token.claims or {}
    sub = claims.get("sub") or token.subject or "unknown"
    kind = claims.get("rh_identity_kind", "agent")
    groups = tuple(claims.get("rh_identity_groups") or [])
    scopes = frozenset(token.scopes or set())
    tenant = claims.get("rh_tenant", "default")
    request_id = claims.get("rh_request_id")

    return Identity(
        sub=sub,
        kind=kind,
        groups=groups,
        scopes=scopes,
        tenant=tenant,
        request_id=request_id,
    )
