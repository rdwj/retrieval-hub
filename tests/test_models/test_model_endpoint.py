"""Tests for the ``ModelEndpoint`` model."""

from __future__ import annotations

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from retrieval_hub.models.model_endpoint import ModelEndpoint
from tests.conftest import make_model_endpoint


def test_model_endpoint_insert_and_query(session: Session) -> None:
    """Model endpoints persist and are queryable by model_name."""
    ep = make_model_endpoint(
        session,
        model_name="acme/embed-v1",
        endpoint_url="http://acme-embed:8000",
        status="healthy",
    )
    session.commit()

    rows = (
        session.execute(
            select(ModelEndpoint).where(
                ModelEndpoint.model_name == "acme/embed-v1"
            )
        )
        .scalars()
        .all()
    )
    assert len(rows) == 1
    assert rows[0].endpoint_url == "http://acme-embed:8000"
    assert rows[0].status == "healthy"
    assert rows[0].id == ep.id


def test_model_endpoint_unique_model_name(session: Session) -> None:
    """Duplicate model_name raises IntegrityError."""
    make_model_endpoint(session, model_name="dup/model")
    session.commit()

    with pytest.raises(IntegrityError):
        make_model_endpoint(session, model_name="dup/model")
    session.rollback()


def test_model_endpoint_nullable_last_probed(session: Session) -> None:
    """last_probed starts as None."""
    ep = make_model_endpoint(session, model_name="probe-test/v1")
    session.commit()

    fetched = session.get(ModelEndpoint, ep.id)
    assert fetched is not None
    assert fetched.last_probed is None
