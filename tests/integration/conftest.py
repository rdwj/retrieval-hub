"""Integration test fixtures — skip unless live databases are reachable."""

from __future__ import annotations

import os

import pytest
from sqlalchemy import Engine
from sqlalchemy.orm import Session

from retrieval_hub.db.engine import create_db_engine, make_session_factory

CATALOG_DB_URL = os.environ.get(
    "RETRIEVAL_HUB_DB_URL",
    "postgresql+psycopg://retrievalhub:retrievalhub@127.0.0.1:5434/retrievalhub",
)
VECTORS_DB_URL = os.environ.get(
    "RETRIEVAL_HUB_VECTORS_DB_URL",
    "postgresql+psycopg://retrievalhub:retrievalhub@127.0.0.1:5433/retrievalhub_vectors",
)
EMBEDDING_ENDPOINT = os.environ.get(
    "RETRIEVAL_HUB_EMBEDDING_ENDPOINT",
    "http://127.0.0.1:8080",
)
MEMGRAPH_URI = os.environ.get("MEMGRAPH_BOLT_URI", "bolt://127.0.0.1:17687")


def _can_connect(url: str) -> bool:
    """Quick TCP probe — True if the host:port accepts a connection."""
    import socket
    from urllib.parse import urlparse

    parsed = urlparse(url.replace("+psycopg", ""))
    host = parsed.hostname or "127.0.0.1"
    port = parsed.port or 5432
    try:
        with socket.create_connection((host, port), timeout=2):
            return True
    except OSError:
        return False


_skip_reason = (
    "Integration tests require port-forwards to the cluster databases. "
    "Set RETRIEVAL_HUB_DB_URL / RETRIEVAL_HUB_VECTORS_DB_URL or run:\n"
    "  oc port-forward svc/retrieval-hub-pg 5434:5432 -n retrieval-hub\n"
    "  oc port-forward svc/retrieval-hub-pg 5433:5432 -n retrieval-hub\n"
    "  oc port-forward svc/retrieval-hub-embedding-nomic 8080:8080 -n retrieval-hub"
)


def pytest_collection_modifyitems(config, items):
    """Auto-skip integration tests when databases are unreachable."""
    if not _can_connect(CATALOG_DB_URL):
        skip = pytest.mark.skip(reason=_skip_reason)
        for item in items:
            item.add_marker(skip)
        return
    os.environ.setdefault("MEMGRAPH_BOLT_URI", MEMGRAPH_URI)


@pytest.fixture(scope="session")
def catalog_engine() -> Engine:
    """SQLAlchemy engine connected to the live catalog database."""
    return create_db_engine(CATALOG_DB_URL)


@pytest.fixture()
def catalog_session(catalog_engine: Engine) -> Session:
    """Catalog database session for one test."""
    factory = make_session_factory(catalog_engine)
    session = factory()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture(scope="session")
def vectors_db_url() -> str:
    return VECTORS_DB_URL


@pytest.fixture(scope="session")
def embedding_endpoint() -> str:
    return EMBEDDING_ENDPOINT
