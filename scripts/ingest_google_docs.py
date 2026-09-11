#!/usr/bin/env python3
"""Ingest Google Docs from a Drive folder or explicit doc IDs into RetrievalHub."""

from __future__ import annotations

import argparse
import logging
import os
import sys

logging.basicConfig(
    level=logging.INFO,
    format="%(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger(__name__)

DEFAULT_DB_URL = os.getenv(
    "RETRIEVAL_HUB_DB_URL",
    "postgresql+psycopg://retrievalhub:retrievalhub@127.0.0.1:5434/retrievalhub",
)
DEFAULT_VECTORS_DB_URL = os.getenv(
    "RETRIEVAL_HUB_VECTORS_DB_URL",
    "postgresql+psycopg://retrievalhub:retrievalhub@127.0.0.1:5433/retrievalhub_vectors",
)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)

    # Mutually exclusive group for folder vs explicit docs
    source_group = parser.add_mutually_exclusive_group(required=True)
    source_group.add_argument(
        "--folder-id",
        help="Google Drive folder ID to fetch all docs from",
    )
    source_group.add_argument(
        "--doc-ids",
        help="Comma-separated list of Google Doc IDs",
    )

    # Required arguments
    parser.add_argument(
        "--service-account-key",
        required=True,
        help="Path to service account JSON key file",
    )
    parser.add_argument(
        "--slug",
        required=True,
        help="Source slug (URL-safe identifier)",
    )
    parser.add_argument(
        "--name",
        required=True,
        help="Human-readable source name",
    )
    parser.add_argument(
        "--description",
        required=True,
        help="Short description of the source",
    )

    # Optional arguments
    parser.add_argument(
        "--db-url",
        default=DEFAULT_DB_URL,
        help=f"Catalog database URL (default: {DEFAULT_DB_URL})",
    )
    parser.add_argument(
        "--vectors-db-url",
        default=DEFAULT_VECTORS_DB_URL,
        help=f"Vectors database URL (default: {DEFAULT_VECTORS_DB_URL})",
    )
    parser.add_argument(
        "--embedding-model",
        default="nomic-ai/nomic-embed-text-v1.5",
        help="Embedding model name (default: nomic-ai/nomic-embed-text-v1.5)",
    )
    parser.add_argument(
        "--embedding-endpoint",
        help="Remote embedding endpoint URL (optional)",
    )
    parser.add_argument(
        "--chunk-tokens",
        type=int,
        default=512,
        help="Chunk size in tokens (default: 512)",
    )
    parser.add_argument(
        "--table-suffix",
        default="v1",
        help="Table suffix (default: v1)",
    )

    args = parser.parse_args()

    # Import here to fail fast if dependencies are missing
    try:
        from retrieval_hub.ingestion.fetch_google_docs import fetch_google_docs
        from retrieval_hub.ingestion.pipeline import ingest
    except ImportError as exc:
        logger.error("Import failed: %s", exc)
        logger.error("Install Google Docs dependencies: pip install 'retrieval-hub[gdocs]'")
        sys.exit(1)

    # Fetch Google Docs
    logger.info("Fetching Google Docs...")
    try:
        docs = fetch_google_docs(
            folder_id=args.folder_id,
            doc_ids=args.doc_ids.split(",") if args.doc_ids else None,
            service_account_key_path=args.service_account_key,
        )
    except Exception as exc:
        logger.error("Fetch failed: %s", exc)
        sys.exit(1)

    if not docs:
        logger.error("No documents fetched; aborting")
        sys.exit(1)

    logger.info("Fetched %d documents", len(docs))

    # Run ingestion pipeline
    logger.info("Running ingestion pipeline...")
    try:
        result = ingest(
            documents=docs,
            data_dir=None,
            slug=args.slug,
            name=args.name,
            family="google_docs",
            description_short=args.description,
            description_long="",
            db_url=args.db_url,
            vectors_db_url=args.vectors_db_url,
            chunk_tokens=args.chunk_tokens,
            overlap_tokens=0,
            embedding_model=args.embedding_model,
            embedding_endpoint=args.embedding_endpoint,
            table_suffix=args.table_suffix,
        )
    except Exception as exc:
        logger.error("Ingestion failed: %s", exc)
        sys.exit(1)

    # Print summary
    print()
    print("=" * 72)
    print("Google Docs ingestion complete")
    print("=" * 72)
    print(f"  Source slug          : {result.source_slug}")
    print(f"  Source UUID          : {result.source_id}")
    print(f"  Documents fetched    : {len(docs)}")
    print(f"  Created new source   : {result.created_source}")
    print("=" * 72)


if __name__ == "__main__":
    main()
