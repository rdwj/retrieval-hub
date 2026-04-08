"""GET /.well-known/jwks.json — JSON Web Key Set endpoint.

Downstream consumers (the MCP server, the UI BFF, the SDK) fetch this
endpoint at startup and cache the result. The response includes every
active key in the service's key ring so rotation windows work: a token
signed by the previous key remains valid until it naturally expires.

Cache-Control is a modest TTL (5 minutes) — long enough to amortize the
JWKS fetch over hundreds of token validations, short enough that a
rotation is visible to consumers within a few minutes.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from retrieval_hub_auth.dependencies import get_key_ring
from retrieval_hub_auth.keys.rotation import KeyRing, build_jwks

router = APIRouter(tags=["discovery"])

CACHE_TTL_SECONDS = 300


@router.get("/.well-known/jwks.json", response_model=None)
async def jwks_endpoint(key_ring: KeyRing = Depends(get_key_ring)) -> Any:
    """Return the JWKS document for the service's active key ring."""
    payload = build_jwks(key_ring)
    return JSONResponse(
        content=payload,
        headers={"Cache-Control": f"public, max-age={CACHE_TTL_SECONDS}"},
    )
