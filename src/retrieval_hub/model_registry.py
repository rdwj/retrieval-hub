"""Internal API for the model endpoint registry."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from retrieval_hub.models.enums import ModelEndpointStatus
from retrieval_hub.models.model_endpoint import ModelEndpoint


class ModelRegistryError(Exception):
    """Base exception for model registry operations."""


class ModelNotFoundError(ModelRegistryError):
    """No model endpoint registered with the given name."""


class ModelUnavailableError(ModelRegistryError):
    """Model endpoint exists but is marked unhealthy."""


def resolve_model(session: Session, model_name: str) -> str:
    """Return the endpoint URL for a healthy or unknown model."""
    endpoint = session.execute(
        select(ModelEndpoint).where(ModelEndpoint.model_name == model_name)
    ).scalar_one_or_none()
    if endpoint is None:
        raise ModelNotFoundError(
            f"No endpoint registered for model {model_name!r}"
        )
    if endpoint.status == ModelEndpointStatus.UNHEALTHY:
        raise ModelUnavailableError(
            f"Model {model_name!r} is marked unhealthy"
        )
    return endpoint.endpoint_url


def register_model(
    session: Session, model_name: str, endpoint_url: str
) -> ModelEndpoint:
    """Upsert a model endpoint registration."""
    endpoint = session.execute(
        select(ModelEndpoint).where(ModelEndpoint.model_name == model_name)
    ).scalar_one_or_none()
    if endpoint is not None:
        endpoint.endpoint_url = endpoint_url
        session.flush()
        return endpoint
    endpoint = ModelEndpoint(
        model_name=model_name,
        endpoint_url=endpoint_url,
        status="unknown",
    )
    session.add(endpoint)
    session.flush()
    return endpoint


def update_model_status(
    session: Session, model_name: str, status: ModelEndpointStatus
) -> None:
    """Set the health status and probe timestamp for a model."""
    endpoint = session.execute(
        select(ModelEndpoint).where(ModelEndpoint.model_name == model_name)
    ).scalar_one_or_none()
    if endpoint is None:
        raise ModelNotFoundError(
            f"No endpoint registered for model {model_name!r}"
        )
    endpoint.status = status
    endpoint.last_probed = datetime.now(UTC)
    session.flush()
