"""Tests for _resolve_embedding_endpoint in retrieval.api.

These tests exercise the registry-aware endpoint resolution introduced in
Phase 3. They use a real (SQLite) DB session so that ``resolve_model``
queries the model_endpoint table, while the RecipeVersion objects are
detached ORM instances whose ``.content`` is read in-process only.
"""

from __future__ import annotations

import pytest

from retrieval_hub.model_registry import ModelUnavailableError
from retrieval_hub.models import RecipeVersion
from retrieval_hub.retrieval.api import _resolve_embedding_endpoint
from tests.conftest import make_model_endpoint


def _make_recipe_version(content: dict) -> RecipeVersion:
    """Build a detached RecipeVersion with the given content dict."""
    return RecipeVersion(
        id="rv1",
        source_id="s1",
        version_number=1,
        content=content,
    )


def test_resolve_embedding_endpoint_from_registry(session):
    """When model is in registry, returns registry endpoint URL."""
    make_model_endpoint(
        session,
        model_name="test/embed-v1",
        endpoint_url="http://registry:8000",
    )
    session.commit()

    rv = _make_recipe_version(
        {"embedding": {"model": "test/embed-v1", "endpoint": "http://recipe:9000"}}
    )
    url = _resolve_embedding_endpoint(session, rv)
    assert url == "http://registry:8000"


def test_resolve_embedding_endpoint_fallback_to_recipe(session):
    """When model is NOT in registry but recipe has endpoint, returns recipe endpoint."""
    rv = _make_recipe_version(
        {"embedding": {"model": "unregistered/model", "endpoint": "http://recipe:9000"}}
    )
    url = _resolve_embedding_endpoint(session, rv)
    assert url == "http://recipe:9000"


def test_resolve_embedding_endpoint_no_registry_no_recipe(session):
    """When model is NOT in registry and recipe has no endpoint, returns None."""
    rv = _make_recipe_version(
        {"embedding": {"model": "unregistered/model"}}
    )
    url = _resolve_embedding_endpoint(session, rv)
    assert url is None


def test_resolve_embedding_endpoint_no_model_in_recipe(session):
    """When recipe has no embedding.model, returns None."""
    rv = _make_recipe_version({"chunker": {"size": 512}})
    url = _resolve_embedding_endpoint(session, rv)
    assert url is None


def test_resolve_embedding_endpoint_unhealthy_model(session):
    """When model is unhealthy, raises ModelUnavailableError (not caught)."""
    make_model_endpoint(
        session,
        model_name="test/embed-v1",
        endpoint_url="http://registry:8000",
        status="unhealthy",
    )
    session.commit()

    rv = _make_recipe_version(
        {"embedding": {"model": "test/embed-v1"}}
    )
    with pytest.raises(ModelUnavailableError):
        _resolve_embedding_endpoint(session, rv)
