"""POST /introspect — RFC 7662 token introspection (debug surface).

This endpoint is useful for operators investigating a specific token: feed
it in, get back the validated claim set. It is **not** the validation
contract for normal traffic — the MCP server and other consumers validate
JWTs locally using the JWKS, not by calling this endpoint.

The endpoint is unauthenticated in this scaffold because it only returns
information about tokens the caller already possesses. A production
deployment should gate it behind operator auth.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Form, status
from fastapi.responses import JSONResponse

from retrieval_hub_auth.dependencies import get_validator
from retrieval_hub_auth.tokens.validator import TokenValidator, ValidationError

router = APIRouter(tags=["oauth"])


@router.post("/introspect", response_model=None)
async def introspect_endpoint(
    token: Annotated[str, Form()],
    validator: TokenValidator = Depends(get_validator),
) -> Any:
    """Return the validated claim set for the given token.

    RFC 7662 says an invalid token should return ``{"active": false}``
    rather than a 4xx. We follow that convention.
    """
    try:
        identity = validator.validate(token)
    except ValidationError:
        return JSONResponse(status_code=status.HTTP_200_OK, content={"active": False})

    return {
        "active": True,
        "sub": identity.sub,
        "scope": " ".join(sorted(identity.scopes)),
        "rh_identity_kind": identity.kind,
        "rh_identity_groups": list(identity.groups),
        "rh_tenant": identity.tenant,
        "jti": identity.jti,
        "iat": identity.issued_at,
        "exp": identity.expires_at,
    }
