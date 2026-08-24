"""Seed the catalog database with currently deployed embedding model endpoints.

Registers each model as a row in the ``model_endpoint`` table so the MCP
server can resolve model names to serving URLs at query time.  The script
is idempotent: ``register_model`` performs an upsert, so running it again
updates endpoints without duplicating rows.

Usage:

    # With local Postgres on the standard dev port-forward:
    python scripts/seed_model_endpoints.py

    # Or with a custom catalog DB URL:
    python scripts/seed_model_endpoints.py \
        --db-url postgresql+psycopg://user:pass@host:port/db
"""

from __future__ import annotations

import argparse
import sys

from sqlalchemy import select

from retrieval_hub.db import create_db_engine, make_session_factory, session_scope
from retrieval_hub.model_registry import register_model
from retrieval_hub.models.model_endpoint import ModelEndpoint

DEFAULT_DB_URL = (
    "postgresql+psycopg://retrievalhub:retrievalhub@127.0.0.1:5434/retrievalhub"
)

MODELS = [
    {
        "model_name": "Snowflake/snowflake-arctic-embed-m-v1.5",
        "endpoint_url": "http://vllm-snowflake-embedding.retrieval-hub.svc.cluster.local:8000",
    },
    {
        "model_name": "NeuML/pubmedbert-base-embeddings",
        "endpoint_url": "http://retrieval-hub-embedding.retrieval-hub.svc.cluster.local:8080",
    },
    {
        "model_name": "nomic-ai/nomic-embed-text-v1.5",
        "endpoint_url": "http://retrieval-hub-embedding-nomic.retrieval-hub.svc.cluster.local:8080",
    },
]


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Register deployed embedding model endpoints in the catalog database.",
    )
    parser.add_argument(
        "--db-url",
        default=DEFAULT_DB_URL,
        help=f"SQLAlchemy URL for the catalog database (default: {DEFAULT_DB_URL})",
    )
    args = parser.parse_args()

    engine = create_db_engine(args.db_url)
    factory = make_session_factory(engine)

    with session_scope(factory) as session:
        for entry in MODELS:
            name = entry["model_name"]
            url = entry["endpoint_url"]

            existing = session.execute(
                select(ModelEndpoint).where(ModelEndpoint.model_name == name)
            ).scalar_one_or_none()

            endpoint = register_model(session, name, url)
            action = "updated" if existing is not None else "registered"
            print(f"  {action}: {endpoint.model_name} -> {endpoint.endpoint_url}")

    print(f"\n{len(MODELS)} model endpoint(s) seeded successfully.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
