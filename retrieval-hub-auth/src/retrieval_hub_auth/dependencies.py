"""FastAPI dependency providers.

These functions are attached to routes via ``Depends(...)``. Each one pulls
the corresponding service singleton off ``request.app.state.auth_state``,
where it was placed during the app lifespan startup (see
:mod:`retrieval_hub_auth.main`).
"""

from __future__ import annotations

from fastapi import Request

from retrieval_hub_auth.app_state import AppState, InMemoryRateLimiter
from retrieval_hub_auth.backends.base import IdPBackend
from retrieval_hub_auth.keys.rotation import KeyRing
from retrieval_hub_auth.tokens.issuer import TokenIssuer
from retrieval_hub_auth.tokens.validator import TokenValidator


def get_app_state(request: Request) -> AppState:
    """Return the ``AppState`` attached to this app."""
    state: AppState = request.app.state.auth_state
    return state


def get_key_ring(request: Request) -> KeyRing:
    """Return the active key ring."""
    return get_app_state(request).key_ring


def get_backend(request: Request) -> IdPBackend:
    """Return the active IdP backend."""
    return get_app_state(request).backend


def get_issuer(request: Request) -> TokenIssuer:
    """Return the token issuer."""
    return get_app_state(request).issuer


def get_validator(request: Request) -> TokenValidator:
    """Return the token validator."""
    return get_app_state(request).validator


def get_rate_limiter(request: Request) -> InMemoryRateLimiter:
    """Return the in-memory rate limiter."""
    return get_app_state(request).rate_limiter
