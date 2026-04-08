"""HTTP route modules for retrieval-hub-auth.

Each sub-module owns one logical endpoint group. The routes are wired into
the FastAPI app in :mod:`retrieval_hub_auth.main`.
"""

from __future__ import annotations

from retrieval_hub_auth.routes.health import router as health_router
from retrieval_hub_auth.routes.introspect import router as introspect_router
from retrieval_hub_auth.routes.jwks import router as jwks_router
from retrieval_hub_auth.routes.token import router as token_router

__all__ = ["health_router", "introspect_router", "jwks_router", "token_router"]
