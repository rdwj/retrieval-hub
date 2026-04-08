"""Pydantic models for retrieval-hub-auth token shapes.

This module is the single authoritative place for the JWT claim layout, the
scope vocabulary, and the ``/token`` request / response bodies. Every other
module in the service imports from here rather than inlining claim-name
strings.

The claim shape follows ``docs/auth.md`` exactly.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

# ---------------------------------------------------------------------------
# The finite scope vocabulary (see docs/auth.md §"Token shape")
# ---------------------------------------------------------------------------

SCOPE_SOURCES_LIST = "sources.list"
SCOPE_SOURCES_READ = "sources.read"
SCOPE_SOURCES_QUERY = "sources.query"
SCOPE_SOURCES_WRITE = "sources.write"
SCOPE_REWRITE_INVOKE = "rewrite.invoke"
SCOPE_ADMIN_READ = "admin.read"
SCOPE_ADMIN_WRITE = "admin.write"

SCOPES_ALL: frozenset[str] = frozenset(
    {
        SCOPE_SOURCES_LIST,
        SCOPE_SOURCES_READ,
        SCOPE_SOURCES_QUERY,
        SCOPE_SOURCES_WRITE,
        SCOPE_REWRITE_INVOKE,
        SCOPE_ADMIN_READ,
        SCOPE_ADMIN_WRITE,
    }
)

# Identity kinds that are never allowed to receive the admin.write scope.
# See the hard rule in docs/auth.md ("admin.write is never issued to agent
# identities under any IdP backend"). Enforced in code, not configuration.
NON_ADMIN_IDENTITY_KINDS: frozenset[str] = frozenset({"agent", "service"})


# ---------------------------------------------------------------------------
# JWT claim model
# ---------------------------------------------------------------------------


class TokenClaims(BaseModel):
    """Typed representation of a retrieval-hub JWT's claim set.

    Mirrors the shape documented in ``docs/auth.md``. The field order in
    this model is intentional: standard claims first, then the ``rh_*``
    extension claims.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    # Standard OIDC/OAuth claims
    iss: str = Field(description="Issuer URL")
    aud: str = Field(description="Audience (who the token is for)")
    sub: str = Field(description="Structured subject, ``<kind>:<id>``")
    iat: int = Field(description="Issued-at (Unix seconds)")
    nbf: int = Field(description="Not-before (Unix seconds)")
    exp: int = Field(description="Expiry (Unix seconds)")
    jti: str = Field(description="Unique token id, prefixed ``tok_``")
    scope: str = Field(description="Space-separated list of granted scopes")

    # retrieval-hub extension claims
    rh_identity_kind: Literal["user", "agent", "service", "client"] = Field(
        description="Identity kind; mirrors the ``sub`` prefix.",
    )
    rh_identity_groups: list[str] = Field(
        default_factory=list,
        description="Group memberships from the IdP; opaque strings.",
    )
    rh_tenant: str = Field(
        default="default",
        description="Tenant scope; v1 is single-tenant (``default``).",
    )
    rh_caller_app: str | None = Field(
        default=None,
        description="Optional human label for the calling application.",
    )
    rh_request_id: str | None = Field(
        default=None,
        description="Optional request id for tracing.",
    )


# ---------------------------------------------------------------------------
# /token request body
# ---------------------------------------------------------------------------


class ClientCredentialsRequest(BaseModel):
    """OAuth 2.1 client_credentials grant form body.

    The scope parameter is optional; when omitted the issuer returns the
    client's default scopes.
    """

    model_config = ConfigDict(extra="forbid")

    grant_type: str
    client_id: str
    client_secret: str
    scope: str | None = None


# ---------------------------------------------------------------------------
# /token response body
# ---------------------------------------------------------------------------


class TokenResponse(BaseModel):
    """Standard OAuth 2.0 token endpoint response."""

    model_config = ConfigDict(extra="forbid")

    access_token: str
    token_type: Literal["Bearer"] = "Bearer"
    expires_in: int
    scope: str
