"""FastAPI application factory and entrypoint for retrieval-hub-auth.

Responsibilities:

* Build the FastAPI app
* On startup: load configuration, open the database, load or generate key
  material, construct the IdP backend, wire the token issuer and validator,
  and attach everything to ``app.state.auth_state``
* On shutdown: dispose the database engine
* Expose the FastAPI ``app`` object at module level so ``uvicorn
  retrieval_hub_auth.main:app`` works out of the box

Running ``python -m retrieval_hub_auth.main`` starts uvicorn on
``localhost:8000`` for local development; ``make run-dev`` uses that
entrypoint.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from retrieval_hub_auth import __version__
from retrieval_hub_auth.app_state import AppState, InMemoryRateLimiter
from retrieval_hub_auth.backends.local import LocalBackend
from retrieval_hub_auth.config import AuthSettings, get_settings
from retrieval_hub_auth.db.base import Base
from retrieval_hub_auth.db.engine import create_db_engine, make_session_factory
from retrieval_hub_auth.keys.loader import (
    KeyMaterial,
    generate_ephemeral_rsa_keypair,
    load_private_key_pem,
    load_public_key_pem,
)
from retrieval_hub_auth.keys.rotation import KeyRing
from retrieval_hub_auth.logging import configure_logging, get_logger
from retrieval_hub_auth.routes import (
    health_router,
    introspect_router,
    jwks_router,
    token_router,
)
from retrieval_hub_auth.tokens.issuer import TokenIssuer
from retrieval_hub_auth.tokens.validator import TokenValidator

logger = get_logger(__name__)


def build_key_ring(settings: AuthSettings) -> KeyRing:
    """Load signing + validator-only keys per configuration.

    If no signing key is configured and ``generate_ephemeral_keys_if_missing``
    is True, generate an in-process RSA keypair. This is the dev default;
    production deploys must set ``RETRIEVAL_HUB_AUTH_SIGNING_KEY_PATH``.
    """
    if settings.signing_key_path:
        signing_key = load_private_key_pem(settings.signing_key_path)
    elif settings.generate_ephemeral_keys_if_missing:
        logger.warning(
            "No RETRIEVAL_HUB_AUTH_SIGNING_KEY_PATH configured; "
            "generating an ephemeral RSA keypair for this process. "
            "This is only appropriate for development."
        )
        signing_key = generate_ephemeral_rsa_keypair()
    else:
        raise RuntimeError("No signing key configured and ephemeral generation is disabled.")

    additional: list[KeyMaterial] = []
    extra_paths = [
        path.strip() for path in settings.additional_public_key_paths.split(",") if path.strip()
    ]
    for path in extra_paths:
        additional.append(load_public_key_pem(path))

    return KeyRing(signing_key=signing_key, additional_keys=additional)


def build_app_state(settings: AuthSettings) -> AppState:
    """Assemble every long-lived object the service needs."""
    configure_logging(settings.log_level)

    engine = create_db_engine(settings.db_url)
    Base.metadata.create_all(engine)
    session_factory = make_session_factory(engine)

    key_ring = build_key_ring(settings)

    backend = LocalBackend(session_factory=session_factory)

    issuer = TokenIssuer(
        key_ring=key_ring,
        issuer=settings.issuer,
        audience=settings.audience,
        default_lifetime_seconds=settings.default_token_lifetime_seconds,
        session_factory=session_factory,
        backend_name=settings.backend,
    )

    validator = TokenValidator(
        key_ring=key_ring,
        issuer=settings.issuer,
        audience=settings.audience,
    )

    rate_limiter = InMemoryRateLimiter(settings.rate_limit_per_client_per_minute)

    return AppState(
        settings=settings,
        engine=engine,
        session_factory=session_factory,
        key_ring=key_ring,
        backend=backend,
        issuer=issuer,
        validator=validator,
        rate_limiter=rate_limiter,
    )


def create_app(state: AppState | None = None) -> FastAPI:
    """Build the FastAPI app and attach service state to ``app.state``.

    Tests inject a pre-built ``AppState``; production uses the lifespan
    hook below to build one from environment-driven settings.
    """

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        if not hasattr(app.state, "auth_state"):
            settings = get_settings()
            app.state.auth_state = build_app_state(settings)
        logger.info(
            "retrieval-hub-auth started",
            extra={
                "version": __version__,
                "backend": app.state.auth_state.settings.backend,
                "issuer": app.state.auth_state.settings.issuer,
            },
        )
        try:
            yield
        finally:
            app.state.auth_state.engine.dispose()
            logger.info("retrieval-hub-auth shut down")

    app = FastAPI(
        title="retrieval-hub-auth",
        description=(
            "OAuth 2.1 client_credentials token issuer, JWKS endpoint, and "
            "JWT validator for the retrieval-hub platform."
        ),
        version=__version__,
        lifespan=lifespan,
    )

    if state is not None:
        app.state.auth_state = state

    app.include_router(health_router)
    app.include_router(jwks_router)
    app.include_router(token_router)
    app.include_router(introspect_router)

    return app


app = create_app()


def main() -> None:
    """Module entrypoint for ``python -m retrieval_hub_auth.main``."""
    import uvicorn

    uvicorn.run(
        "retrieval_hub_auth.main:app",
        host="127.0.0.1",
        port=8000,
        reload=False,
    )


if __name__ == "__main__":  # pragma: no cover
    main()
