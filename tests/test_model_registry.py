"""Tests for the model registry API (``retrieval_hub.model_registry``)."""

from __future__ import annotations

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from retrieval_hub.model_registry import (
    ModelNotFoundError,
    ModelUnavailableError,
    register_model,
    resolve_model,
    update_model_status,
)
from retrieval_hub.models.model_endpoint import ModelEndpoint
from tests.conftest import make_model_endpoint


def test_resolve_model_returns_url(session: Session) -> None:
    """resolve_model returns endpoint_url for a healthy model."""
    make_model_endpoint(
        session,
        model_name="m/v1",
        endpoint_url="http://host:8000",
        status="healthy",
    )
    session.commit()
    url = resolve_model(session, "m/v1")
    assert url == "http://host:8000"


def test_resolve_model_unknown_status_succeeds(session: Session) -> None:
    """resolve_model returns url when status is 'unknown' (not just healthy)."""
    make_model_endpoint(session, model_name="m/v1", status="unknown")
    session.commit()
    url = resolve_model(session, "m/v1")
    assert "test-embedding" in url


def test_resolve_model_not_found(session: Session) -> None:
    """resolve_model raises ModelNotFoundError for missing model."""
    with pytest.raises(ModelNotFoundError):
        resolve_model(session, "nonexistent/model")


def test_resolve_model_unhealthy(session: Session) -> None:
    """resolve_model raises ModelUnavailableError for unhealthy model."""
    make_model_endpoint(session, model_name="m/v1", status="unhealthy")
    session.commit()
    with pytest.raises(ModelUnavailableError):
        resolve_model(session, "m/v1")


def test_register_model_creates_new(session: Session) -> None:
    """register_model creates a new row when model_name doesn't exist."""
    ep = register_model(session, "new/model", "http://new:8000")
    session.commit()
    assert ep.model_name == "new/model"
    assert ep.endpoint_url == "http://new:8000"
    assert ep.status == "unknown"


def test_register_model_upserts_existing(session: Session) -> None:
    """register_model updates endpoint_url for existing model_name."""
    register_model(session, "m/v1", "http://old:8000")
    session.commit()
    ep = register_model(session, "m/v1", "http://new:9000")
    session.commit()
    assert ep.endpoint_url == "http://new:9000"


def test_update_model_status_changes_status(session: Session) -> None:
    """update_model_status sets status and last_probed."""
    make_model_endpoint(session, model_name="m/v1")
    session.commit()
    update_model_status(session, "m/v1", "healthy")
    session.commit()

    ep = session.execute(
        select(ModelEndpoint).where(ModelEndpoint.model_name == "m/v1")
    ).scalar_one()
    assert ep.status == "healthy"
    assert ep.last_probed is not None


def test_update_model_status_not_found(session: Session) -> None:
    """update_model_status raises ModelNotFoundError for missing model."""
    with pytest.raises(ModelNotFoundError):
        update_model_status(session, "nonexistent/model", "healthy")
