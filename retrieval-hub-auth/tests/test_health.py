"""Tests for /health and /ready."""

from __future__ import annotations

from fastapi.testclient import TestClient

from retrieval_hub_auth.app_state import AppState


def test_health_returns_ok(client: TestClient) -> None:
    response = client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["service"] == "retrieval-hub-auth"


def test_ready_returns_ok_when_db_reachable(client: TestClient) -> None:
    response = client.get("/ready")
    assert response.status_code == 200
    assert response.json()["status"] == "ready"


def test_ready_returns_503_when_db_unreachable(client: TestClient, app_state: AppState) -> None:
    app_state.engine.dispose()
    # Replace the engine with one pointing at a path that fails on connect
    from retrieval_hub_auth.db.engine import create_db_engine

    broken = create_db_engine("sqlite+pysqlite:////nonexistent/path/to/db.sqlite")
    app_state.engine = broken

    response = client.get("/ready")
    assert response.status_code == 503
    assert response.json()["status"] == "not_ready"
