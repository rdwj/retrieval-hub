"""Token issuance and validation for retrieval-hub-auth.

Three modules:

* :mod:`retrieval_hub_auth.tokens.claims` — Pydantic models for the JWT
  claim shape and the client-credentials request body.
* :mod:`retrieval_hub_auth.tokens.issuer` — mint new JWTs, enforce the
  ``admin.write`` guard, write the audit log.
* :mod:`retrieval_hub_auth.tokens.validator` — validate JWTs against a
  :class:`~retrieval_hub_auth.keys.rotation.KeyRing`. Used by downstream
  consumers like ``retrieval-hub-mcp``.
"""

from __future__ import annotations

from retrieval_hub_auth.tokens.claims import (
    SCOPE_ADMIN_WRITE,
    SCOPES_ALL,
    ClientCredentialsRequest,
    TokenClaims,
    TokenResponse,
)
from retrieval_hub_auth.tokens.issuer import (
    AdminWriteForbiddenError,
    InvalidScopeError,
    IssuanceError,
    TokenIssuer,
)
from retrieval_hub_auth.tokens.validator import (
    InvalidAudienceError,
    InvalidIssuerError,
    InvalidSignatureError,
    TokenExpiredError,
    TokenValidator,
    UnknownKeyError,
    ValidatedIdentity,
    ValidationError,
)

__all__ = [
    "SCOPES_ALL",
    "SCOPE_ADMIN_WRITE",
    "AdminWriteForbiddenError",
    "ClientCredentialsRequest",
    "InvalidAudienceError",
    "InvalidIssuerError",
    "InvalidScopeError",
    "InvalidSignatureError",
    "IssuanceError",
    "TokenClaims",
    "TokenExpiredError",
    "TokenIssuer",
    "TokenResponse",
    "TokenValidator",
    "UnknownKeyError",
    "ValidatedIdentity",
    "ValidationError",
]
