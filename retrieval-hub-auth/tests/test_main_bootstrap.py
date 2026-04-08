"""Tests for the application bootstrap (main.py).

These exercise the code path that runs when FastAPI builds the service from
raw configuration: loading settings, generating ephemeral keys, wiring the
issuer and validator, and the lifespan startup / shutdown hooks.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from retrieval_hub_auth.config import AuthSettings
from retrieval_hub_auth.keys.loader import (
    generate_ephemeral_rsa_keypair,
    private_key_to_pem_bytes,
    public_key_to_pem_bytes,
)
from retrieval_hub_auth.main import build_app_state, build_key_ring, create_app


def test_build_key_ring_generates_ephemeral_when_no_path() -> None:
    settings = AuthSettings(
        signing_key_path=None,
        generate_ephemeral_keys_if_missing=True,
    )
    ring = build_key_ring(settings)
    assert ring.signing_key.can_sign


def test_build_key_ring_refuses_when_no_key_and_no_ephemeral() -> None:
    settings = AuthSettings(
        signing_key_path=None,
        generate_ephemeral_keys_if_missing=False,
    )
    with pytest.raises(RuntimeError):
        build_key_ring(settings)


def test_build_key_ring_loads_from_disk(tmp_path: Path) -> None:
    signing = generate_ephemeral_rsa_keypair()
    signing_path = tmp_path / "signing.pem"
    signing_path.write_bytes(private_key_to_pem_bytes(signing))

    extra = generate_ephemeral_rsa_keypair()
    extra_path = tmp_path / "extra.pem"
    extra_path.write_bytes(public_key_to_pem_bytes(extra))

    settings = AuthSettings(
        signing_key_path=str(signing_path),
        additional_public_key_paths=str(extra_path),
    )
    ring = build_key_ring(settings)
    assert ring.signing_key.kid == signing.kid
    assert ring.contains(extra.kid)


def test_build_app_state_wires_every_component(tmp_path: Path) -> None:
    db_path = tmp_path / "test.sqlite"
    settings = AuthSettings(
        db_url=f"sqlite+pysqlite:///{db_path}",
        generate_ephemeral_keys_if_missing=True,
    )
    state = build_app_state(settings)
    try:
        assert state.backend.name == "local"
        assert state.issuer is not None
        assert state.validator is not None
        assert state.rate_limiter is not None
    finally:
        state.engine.dispose()


def test_create_app_uses_lifespan_when_no_state_injected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Covers the lifespan path that constructs state from settings."""
    db_path = tmp_path / "lifespan.sqlite"
    monkeypatch.setenv("RETRIEVAL_HUB_AUTH_DB_URL", f"sqlite+pysqlite:///{db_path}")
    monkeypatch.setenv("RETRIEVAL_HUB_AUTH_ISSUER", "https://auth.retrieval-hub.test/")
    monkeypatch.setenv("RETRIEVAL_HUB_AUTH_AUDIENCE", "retrieval-hub")

    # Clear the get_settings cache so env vars take effect.
    from retrieval_hub_auth.config import reset_settings_cache

    reset_settings_cache()

    app = create_app(state=None)
    with TestClient(app) as client:
        response = client.get("/health")
        assert response.status_code == 200
    reset_settings_cache()
