"""Shared pytest fixtures for retrieval-hub-auth tests.

Every test runs against an in-memory SQLite database and ephemeral RSA
keys generated per session. We build the ``AppState`` and the FastAPI
``TestClient`` with these test-scoped dependencies so no test ever touches
real Postgres or real key material.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from retrieval_hub_auth.app_state import AppState, InMemoryRateLimiter
from retrieval_hub_auth.backends.local import LocalBackend
from retrieval_hub_auth.config import AuthSettings
from retrieval_hub_auth.db.base import Base
from retrieval_hub_auth.db.engine import create_db_engine, make_session_factory
from retrieval_hub_auth.db.models import IdentityKind
from retrieval_hub_auth.keys.loader import (
    KeyMaterial,
    generate_ephemeral_rsa_keypair,
)
from retrieval_hub_auth.keys.rotation import KeyRing
from retrieval_hub_auth.main import create_app
from retrieval_hub_auth.tokens.issuer import TokenIssuer
from retrieval_hub_auth.tokens.validator import TokenValidator

TEST_ISSUER = "https://auth.retrieval-hub.test/"
TEST_AUDIENCE = "retrieval-hub"
TEST_RATE_LIMIT = 1000  # effectively disabled for most tests


@pytest.fixture()
def test_signing_key() -> KeyMaterial:
    """A fresh ephemeral RSA keypair for a single test."""
    return generate_ephemeral_rsa_keypair()


@pytest.fixture()
def extra_public_key() -> KeyMaterial:
    """A second ephemeral keypair (private unused) for rotation tests."""
    return generate_ephemeral_rsa_keypair()


@pytest.fixture()
def key_ring(test_signing_key: KeyMaterial) -> KeyRing:
    """A KeyRing containing just the test signing key."""
    return KeyRing(signing_key=test_signing_key)


@pytest.fixture()
def app_state(
    key_ring: KeyRing,
) -> AppState:
    """Build a fully-wired AppState backed by in-memory SQLite."""
    settings = AuthSettings(
        db_url="sqlite+pysqlite:///:memory:",
        issuer=TEST_ISSUER,
        audience=TEST_AUDIENCE,
        default_token_lifetime_seconds=900,
        backend="local",
        generate_ephemeral_keys_if_missing=True,
        rate_limit_per_client_per_minute=TEST_RATE_LIMIT,
    )
    engine = create_db_engine(settings.db_url)
    Base.metadata.create_all(engine)
    session_factory = make_session_factory(engine)

    backend = LocalBackend(session_factory=session_factory)
    issuer = TokenIssuer(
        key_ring=key_ring,
        issuer=settings.issuer,
        audience=settings.audience,
        default_lifetime_seconds=settings.default_token_lifetime_seconds,
        session_factory=session_factory,
        backend_name="local",
    )
    validator = TokenValidator(
        key_ring=key_ring,
        issuer=settings.issuer,
        audience=settings.audience,
    )
    rate_limiter = InMemoryRateLimiter(TEST_RATE_LIMIT)

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


@pytest.fixture()
def client(app_state: AppState) -> Iterator[TestClient]:
    """FastAPI TestClient backed by the test AppState."""
    app = create_app(state=app_state)
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture()
def seeded_client_credentials(app_state: AppState) -> dict[str, str]:
    """Register a baseline agent-kind client and return its credentials."""
    credentials = {
        "client_id": "test-agent-01",
        "client_secret": "s3cret-test-value",
    }
    backend: LocalBackend = app_state.backend  # type: ignore[assignment]
    backend.register_client(
        client_id=credentials["client_id"],
        client_secret=credentials["client_secret"],
        client_name="Test Agent",
        identity_kind=IdentityKind.AGENT,
        identity_groups=["agents", "test-group"],
        default_scopes=[
            "sources.list",
            "sources.read",
            "sources.query",
            "rewrite.invoke",
        ],
        tenant="default",
    )
    return credentials


@pytest.fixture()
def seeded_user_credentials(app_state: AppState) -> dict[str, str]:
    """Register a baseline user-kind admin client and return its credentials."""
    credentials = {
        "client_id": "test-admin-01",
        "client_secret": "s3cret-admin-value",
    }
    backend: LocalBackend = app_state.backend  # type: ignore[assignment]
    backend.register_client(
        client_id=credentials["client_id"],
        client_secret=credentials["client_secret"],
        client_name="Test Admin",
        identity_kind=IdentityKind.USER,
        identity_groups=["admins"],
        default_scopes=[
            "sources.list",
            "sources.read",
            "sources.query",
            "sources.write",
            "rewrite.invoke",
            "admin.read",
            "admin.write",
        ],
        tenant="default",
    )
    return credentials
