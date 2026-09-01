"""Identity extraction from FastMCP access tokens.

Converts FastMCP's ``AccessToken`` (populated by ``JWTVerifier`` or
``GoogleTokenVerifier`` middleware) into the core library's ``Identity``
dataclass so the policy module can make access decisions.
"""

from __future__ import annotations

import logging

from fastmcp.server.dependencies import get_access_token

from retrieval_hub.models.identity import Identity

logger = logging.getLogger(__name__)

_ALLOWED_EMAIL_DOMAIN = "redhat.com"


def get_current_identity() -> Identity | None:
    """Build an ``Identity`` from the current request's access token.

    Returns ``None`` when auth is disabled (no auth provider configured),
    which lets callers skip policy checks for backward compatibility.
    """
    token = get_access_token()
    if token is None:
        return None

    claims = token.claims or {}

    email = claims.get("email")
    if email and not claims.get("rh_identity_kind"):
        return _identity_from_google(claims, token, email)

    return _identity_from_jwt(claims, token)


def _identity_from_google(
    claims: dict, token: object, email: str
) -> Identity:
    """Build an Identity from a Google OAuth token."""
    domain = email.rsplit("@", 1)[-1].lower() if "@" in email else ""
    if domain != _ALLOWED_EMAIL_DOMAIN:
        logger.warning(
            "Google OAuth login rejected: email %s not in domain %s",
            email,
            _ALLOWED_EMAIL_DOMAIN,
        )
        raise PermissionError(
            f"Only @{_ALLOWED_EMAIL_DOMAIN} accounts may authenticate. "
            f"Got: {email}"
        )

    email_verified = claims.get("email_verified")
    if email_verified is not None and str(email_verified).lower() not in (
        "true",
        "1",
    ):
        logger.warning("Google OAuth login rejected: email %s not verified", email)
        raise PermissionError(f"Email {email} is not verified by Google.")

    sub = claims.get("sub") or email

    return Identity(
        sub=f"google:{sub}",
        kind="user",
        groups=(),
        scopes=frozenset(token.scopes or set()),
        tenant="default",
        request_id=None,
        email=email.lower(),
    )


def _identity_from_jwt(claims: dict, token: object) -> Identity:
    """Build an Identity from a retrieval-hub-auth JWT."""
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
