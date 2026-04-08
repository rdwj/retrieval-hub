"""Tests for ``GET /.well-known/jwks.json``."""

from __future__ import annotations

from fastapi.testclient import TestClient

from retrieval_hub_auth.app_state import AppState
from retrieval_hub_auth.keys.loader import generate_ephemeral_rsa_keypair
from retrieval_hub_auth.keys.rotation import KeyRing


def test_jwks_structure_is_valid(client: TestClient, app_state: AppState) -> None:
    response = client.get("/.well-known/jwks.json")
    assert response.status_code == 200
    body = response.json()
    assert "keys" in body
    assert len(body["keys"]) == 1
    key = body["keys"][0]
    assert key["kty"] == "RSA"
    assert key["use"] == "sig"
    assert key["alg"] == "RS256"
    assert key["kid"] == app_state.key_ring.signing_key.kid
    assert "n" in key
    assert "e" in key


def test_jwks_includes_all_rotation_keys(client: TestClient, app_state: AppState) -> None:
    """A key ring with multiple entries exposes all of them."""
    second = generate_ephemeral_rsa_keypair()
    third = generate_ephemeral_rsa_keypair()
    app_state.key_ring = KeyRing(
        signing_key=app_state.key_ring.signing_key,
        additional_keys=[second, third],
    )

    response = client.get("/.well-known/jwks.json")
    assert response.status_code == 200
    body = response.json()
    kids = {k["kid"] for k in body["keys"]}
    assert len(body["keys"]) == 3
    assert second.kid in kids
    assert third.kid in kids
    # Signing key must appear first for naive consumers.
    assert body["keys"][0]["kid"] == app_state.key_ring.signing_key.kid


def test_jwks_sets_cache_control_header(client: TestClient) -> None:
    response = client.get("/.well-known/jwks.json")
    cache_control = response.headers.get("cache-control", "")
    assert "max-age" in cache_control
