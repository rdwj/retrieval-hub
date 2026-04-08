"""Tests for ``POST /token`` — the OAuth 2.1 client_credentials endpoint."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from retrieval_hub_auth.app_state import AppState, InMemoryRateLimiter
from retrieval_hub_auth.backends.local import LocalBackend
from retrieval_hub_auth.db.models import IdentityKind


def _form(body: dict[str, str]) -> dict[str, str]:
    """Helper: turn a dict into form data for TestClient."""
    return body


def test_valid_credentials_return_bearer_token(
    client: TestClient, seeded_client_credentials: dict[str, str]
) -> None:
    response = client.post(
        "/token",
        data=_form(
            {
                "grant_type": "client_credentials",
                "client_id": seeded_client_credentials["client_id"],
                "client_secret": seeded_client_credentials["client_secret"],
            }
        ),
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["token_type"] == "Bearer"
    assert payload["expires_in"] == 900
    assert "sources.list" in payload["scope"]
    assert payload["access_token"]
    # JWT is a three-segment token
    assert payload["access_token"].count(".") == 2


def test_unknown_client_id_returns_401(client: TestClient) -> None:
    response = client.post(
        "/token",
        data=_form(
            {
                "grant_type": "client_credentials",
                "client_id": "not-registered",
                "client_secret": "whatever",
            }
        ),
    )
    assert response.status_code == 401
    assert response.json()["error"] == "invalid_client"


def test_wrong_secret_returns_401(
    client: TestClient, seeded_client_credentials: dict[str, str]
) -> None:
    response = client.post(
        "/token",
        data=_form(
            {
                "grant_type": "client_credentials",
                "client_id": seeded_client_credentials["client_id"],
                "client_secret": "wrong",
            }
        ),
    )
    assert response.status_code == 401
    assert response.json()["error"] == "invalid_client"


def test_disabled_client_returns_401(
    client: TestClient, app_state: AppState, seeded_client_credentials: dict[str, str]
) -> None:
    backend: LocalBackend = app_state.backend  # type: ignore[assignment]
    backend.disable_client(seeded_client_credentials["client_id"])

    response = client.post(
        "/token",
        data=_form(
            {
                "grant_type": "client_credentials",
                "client_id": seeded_client_credentials["client_id"],
                "client_secret": seeded_client_credentials["client_secret"],
            }
        ),
    )
    assert response.status_code == 401
    assert response.json()["error"] == "invalid_client"


def test_requested_scope_outside_defaults_returns_invalid_scope(
    client: TestClient, seeded_client_credentials: dict[str, str]
) -> None:
    response = client.post(
        "/token",
        data=_form(
            {
                "grant_type": "client_credentials",
                "client_id": seeded_client_credentials["client_id"],
                "client_secret": seeded_client_credentials["client_secret"],
                # the test agent does not have sources.write
                "scope": "sources.list sources.write",
            }
        ),
    )
    assert response.status_code == 400
    assert response.json()["error"] == "invalid_scope"


def test_agent_requesting_admin_write_rejected(client: TestClient, app_state: AppState) -> None:
    """An agent client cannot obtain admin.write even if the IdP backend grants it.

    This exercises the in-code admin.write guard in the issuer. We register
    a misconfigured client that has admin.write in its default scopes (for
    the purposes of this test), and confirm that the issuer still refuses.
    """
    backend: LocalBackend = app_state.backend  # type: ignore[assignment]
    backend.register_client(
        client_id="misconfigured-agent",
        client_secret="s3cret",
        client_name="Misconfigured Agent",
        identity_kind=IdentityKind.AGENT,
        identity_groups=["agents"],
        default_scopes=["sources.list", "admin.write"],
    )

    response = client.post(
        "/token",
        data=_form(
            {
                "grant_type": "client_credentials",
                "client_id": "misconfigured-agent",
                "client_secret": "s3cret",
                "scope": "sources.list admin.write",
            }
        ),
    )
    assert response.status_code == 400
    assert response.json()["error"] == "invalid_scope"
    assert "admin.write" in response.json()["error_description"]


def test_empty_scope_request_returns_defaults(
    client: TestClient, seeded_client_credentials: dict[str, str]
) -> None:
    response = client.post(
        "/token",
        data=_form(
            {
                "grant_type": "client_credentials",
                "client_id": seeded_client_credentials["client_id"],
                "client_secret": seeded_client_credentials["client_secret"],
                "scope": "",
            }
        ),
    )
    assert response.status_code == 200
    scope = response.json()["scope"]
    for expected in ["sources.list", "sources.read", "sources.query", "rewrite.invoke"]:
        assert expected in scope


def test_rate_limit_returns_429(
    client: TestClient, app_state: AppState, seeded_client_credentials: dict[str, str]
) -> None:
    # Replace the state's limiter with a tight one
    app_state.rate_limiter = InMemoryRateLimiter(requests_per_minute=2)

    for _ in range(2):
        ok = client.post(
            "/token",
            data=_form(
                {
                    "grant_type": "client_credentials",
                    "client_id": seeded_client_credentials["client_id"],
                    "client_secret": seeded_client_credentials["client_secret"],
                }
            ),
        )
        assert ok.status_code == 200

    blocked = client.post(
        "/token",
        data=_form(
            {
                "grant_type": "client_credentials",
                "client_id": seeded_client_credentials["client_id"],
                "client_secret": seeded_client_credentials["client_secret"],
            }
        ),
    )
    assert blocked.status_code == 429
    assert blocked.json()["error"] == "rate_limited"


def test_unsupported_grant_type_returns_400(
    client: TestClient, seeded_client_credentials: dict[str, str]
) -> None:
    response = client.post(
        "/token",
        data=_form(
            {
                "grant_type": "password",
                "client_id": seeded_client_credentials["client_id"],
                "client_secret": seeded_client_credentials["client_secret"],
            }
        ),
    )
    assert response.status_code == 400
    assert response.json()["error"] == "unsupported_grant_type"


@pytest.mark.parametrize(
    "missing_field",
    ["grant_type", "client_id", "client_secret"],
)
def test_missing_required_field_returns_422(
    client: TestClient,
    seeded_client_credentials: dict[str, str],
    missing_field: str,
) -> None:
    body = {
        "grant_type": "client_credentials",
        "client_id": seeded_client_credentials["client_id"],
        "client_secret": seeded_client_credentials["client_secret"],
    }
    body.pop(missing_field)
    response = client.post("/token", data=_form(body))
    # FastAPI returns 422 for missing form fields; this is distinct from
    # OAuth error responses, which require the request to at least parse.
    assert response.status_code == 422
