"""POST /token — OAuth 2.1 client_credentials grant endpoint.

The request body is ``application/x-www-form-urlencoded`` per RFC 6749
§4.4.2. The response body follows the standard OAuth 2.0 token response
shape, restricted to what retrieval-hub actually issues (``Bearer`` tokens
only, no refresh tokens — tokens are short-lived and callers re-auth).

Error responses follow RFC 6749 §5.2: ``{"error": "invalid_client", ...}``
with an appropriate status code.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Form, Request, status
from fastapi.responses import JSONResponse

from retrieval_hub_auth.app_state import InMemoryRateLimiter
from retrieval_hub_auth.backends.base import (
    DisabledClientError,
    IdPBackend,
    InvalidClientError,
    UnknownClientError,
)
from retrieval_hub_auth.dependencies import (
    get_backend,
    get_issuer,
    get_rate_limiter,
)
from retrieval_hub_auth.logging import get_logger
from retrieval_hub_auth.tokens.claims import TokenResponse
from retrieval_hub_auth.tokens.issuer import (
    AdminWriteForbiddenError,
    InvalidScopeError,
    TokenIssuer,
)

router = APIRouter(tags=["oauth"])
logger = get_logger(__name__)

SUPPORTED_GRANT_TYPE = "client_credentials"


def _oauth_error(
    status_code: int,
    error: str,
    description: str,
) -> JSONResponse:
    """Return an OAuth 2.0 §5.2-compliant error response."""
    return JSONResponse(
        status_code=status_code,
        content={"error": error, "error_description": description},
    )


@router.post("/token", response_model=None)
async def token_endpoint(
    request: Request,
    grant_type: Annotated[str, Form()],
    client_id: Annotated[str, Form()],
    client_secret: Annotated[str, Form()],
    scope: Annotated[str | None, Form()] = None,
    backend: IdPBackend = Depends(get_backend),
    issuer: TokenIssuer = Depends(get_issuer),
    rate_limiter: InMemoryRateLimiter = Depends(get_rate_limiter),
) -> Any:
    """OAuth 2.1 ``client_credentials`` grant.

    See RFC 6749 §4.4 for the protocol shape. retrieval-hub-auth is
    deliberately narrow: ``client_credentials`` is the only grant we
    implement in v0; interactive human auth goes through the UI's BFF.
    """
    # Rate limiting is per-client. IP-based limiting would also be nice but
    # it's a later addition; for now a misbehaving client is what we care
    # about most.
    if not rate_limiter.check(client_id):
        logger.warning("Rate limit exceeded on /token", extra={"client_id": client_id})
        return _oauth_error(
            status.HTTP_429_TOO_MANY_REQUESTS,
            "rate_limited",
            "Too many token requests for this client; please slow down.",
        )

    if grant_type != SUPPORTED_GRANT_TYPE:
        return _oauth_error(
            status.HTTP_400_BAD_REQUEST,
            "unsupported_grant_type",
            f"Only '{SUPPORTED_GRANT_TYPE}' is supported.",
        )

    try:
        principal = backend.authenticate_client(client_id, client_secret)
    except (UnknownClientError, InvalidClientError, DisabledClientError) as exc:
        logger.info(
            "Client authentication failed",
            extra={"client_id": client_id, "reason": type(exc).__name__},
        )
        return _oauth_error(
            status.HTTP_401_UNAUTHORIZED,
            "invalid_client",
            "Client authentication failed.",
        )

    requested_scopes: frozenset[str] | None = None
    if scope is not None:
        requested_scopes = frozenset(s for s in scope.split() if s)

    try:
        issued = issuer.issue(
            principal,
            requested_scopes=requested_scopes,
            client_ip=request.client.host if request.client is not None else None,
            user_agent=request.headers.get("user-agent"),
        )
    except (InvalidScopeError, AdminWriteForbiddenError) as exc:
        logger.info(
            "Scope rejected by issuer",
            extra={
                "client_id": client_id,
                "reason": type(exc).__name__,
                "detail": str(exc),
            },
        )
        return _oauth_error(
            status.HTTP_400_BAD_REQUEST,
            "invalid_scope",
            str(exc),
        )

    response = TokenResponse(
        access_token=issued.access_token,
        expires_in=issued.claims.exp - issued.claims.iat,
        scope=issued.claims.scope,
    )
    return response.model_dump()
