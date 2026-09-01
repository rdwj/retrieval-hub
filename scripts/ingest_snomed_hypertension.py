#!/usr/bin/env python3
"""Ingest the SNOMED-CT hypertension subgraph into RetrievalHub.

Expects the subgraph extractor to have already run, producing
nodes.tsv + edges.tsv in the snomed-ct-hypertension directory.

Usage:
    python scripts/ingest_snomed_hypertension.py [--db-url URL] [--vectors-db-url URL]
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from retrieval_hub.ingestion.pipeline import ingest

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(name)s %(levelname)s %(message)s",
)
logger = logging.getLogger(__name__)

DEFAULT_DB_URL = (
    "postgresql+psycopg://retrievalhub:retrievalhub@127.0.0.1:5434/retrievalhub"
)
DEFAULT_VECTORS_DB_URL = (
    "postgresql+psycopg://retrievalhub:retrievalhub@127.0.0.1:5433/retrievalhub_vectors"
)
DATA_DIR = Path(__file__).resolve().parent.parent.parent / (
    "retrieval-hub-data-sources/snomed-ct-hypertension"
)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--db-url", default=DEFAULT_DB_URL,
        help="Catalog database URL",
    )
    parser.add_argument(
        "--vectors-db-url", default=DEFAULT_VECTORS_DB_URL,
        help="Vectors database URL",
    )
    parser.add_argument(
        "--data-dir", type=Path, default=DATA_DIR,
        help="Directory containing nodes.tsv + edges.tsv",
    )
    parser.add_argument(
        "--embedding-batch-size", type=int, default=2,
        help="Embedding batch size (default: 2 for TEI stability)",
    )
    parser.add_argument(
        "--embedding-endpoint",
        help="Override embedding endpoint URL (bypasses model registry)",
    )
    args = parser.parse_args()

    if not args.data_dir.exists():
        print(
            f"Error: data directory not found: {args.data_dir}\n"
            f"Run scripts/extract_snomed_subgraph.py first.",
            file=sys.stderr,
        )
        sys.exit(1)

    nodes_file = args.data_dir / "nodes.tsv"
    edges_file = args.data_dir / "edges.tsv"
    if not nodes_file.exists() or not edges_file.exists():
        print(
            f"Error: nodes.tsv or edges.tsv not found in {args.data_dir}\n"
            f"Run scripts/extract_snomed_subgraph.py first.",
            file=sys.stderr,
        )
        sys.exit(1)

    logger.info(
        "Starting SNOMED-CT hypertension subgraph ingestion from %s",
        args.data_dir,
    )

    result = ingest(
        data_dir=args.data_dir,
        slug="snomed-ct-hypertension",
        name="SNOMED-CT Hypertension Subgraph",
        family="graph",
        description_short=(
            "Hypertension concept hierarchy from SNOMED-CT US Edition "
            "with clinical relationships and anatomical context"
        ),
        description_long=(
            "Graph-family source extracted from SNOMED-CT US Edition "
            "(September 2026 release). Rooted at Essential hypertension "
            "(59621000) and Hypertensive disorder (38341003), this "
            "subgraph includes the full IS_A descendant hierarchy, "
            "ancestor concepts up to 3 levels, and 1-hop traversals "
            "through Finding site, Associated morphology, Has "
            "definitional manifestation, Has interpretation, Interprets, "
            "Causative agent, and Procedure site relationships. "
            "Supports graph_traverse_from_seed refine strategy for "
            "multi-hop clinical concept expansion."
        ),
        db_url=args.db_url,
        vectors_db_url=args.vectors_db_url,
        chunk_tokens=512,
        overlap_tokens=0,
        embedding_model="nomic-ai/nomic-embed-text-v1.5",
        embedding_endpoint=args.embedding_endpoint,
        embedding_batch_size=args.embedding_batch_size,
        renderer="snomed",
    )

    logger.info(
        "Ingestion complete: slug=%s source_id=%s created=%s",
        result.source_slug, result.source_id, result.created_source,
    )


if __name__ == "__main__":
    main()
