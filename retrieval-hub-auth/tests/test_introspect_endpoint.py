"""Tests for /introspect (RFC 7662 debug surface)."""

from __future__ import annotations

from fastapi.testclient import TestClient


def test_introspect_active_token(
    client: TestClient, seeded_client_credentials: dict[str, str]
) -> None:
    token_response = client.post(
        "/token",
        data={
            "grant_type": "client_credentials",
            "client_id": seeded_client_credentials["client_id"],
            "client_secret": seeded_client_credentials["client_secret"],
        },
    )
    assert token_response.status_code == 200
    access_token = token_response.json()["access_token"]

    response = client.post("/introspect", data={"token": access_token})
    assert response.status_code == 200
    body = response.json()
    assert body["active"] is True
    assert body["sub"] == "agent:test-agent-01"
    assert body["rh_identity_kind"] == "agent"
    assert "sources.list" in body["scope"]
    assert body["jti"].startswith("tok_")


def test_introspect_invalid_token_returns_inactive(client: TestClient) -> None:
    response = client.post("/introspect", data={"token": "not-a-real-jwt"})
    assert response.status_code == 200
    assert response.json() == {"active": False}
