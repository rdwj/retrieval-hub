"""Import AutoRAG evaluation results into the retrieval-hub catalog.

Stores the results of the AutoRAG chunking sweep as EvalSuite, EvalRun,
and EvalResult records in the catalog database.  The sweep compared five
chunking configurations (Token/Sentence x sizes x overlaps) against the
VA CPG clinical guidelines corpus using PubMedBERT embeddings.

Usage:

    # With port-forward to the catalog DB already running on :5434
    python scripts/import_eval_results.py

    # Or with a custom DB URL
    python scripts/import_eval_results.py \
        --db-url postgresql+psycopg://user:pass@host:5432/db
"""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import UTC, datetime

from sqlalchemy import select

from retrieval_hub.db.engine import create_db_engine, make_session_factory
from retrieval_hub.models.enums import (
    EvalRunStatus,
    EvalSuiteFamily,
    ExecutionBackend,
    TriggeredByKind,
)
from retrieval_hub.models.eval import EvalResult, EvalRun, EvalSuite
from retrieval_hub.models.source import PhysicalIndex, Source

logger = logging.getLogger("import_eval_results")

DEFAULT_DB_URL = "postgresql+psycopg://retrievalhub:retrievalhub@127.0.0.1:5434/retrievalhub"

SOURCE_SLUG = "va-cpg-clinical-guidelines"
SUITE_SLUG = "autorag-chunking-eval"
SUITE_NAME = "AutoRAG chunking evaluation"
EMBEDDING_MODEL = "NeuML/pubmedbert-base-embeddings"

# AutoRAG sweep results: (case_id, chunker, chunk_size, overlap, hit_rate, mrr, chunk_count)
EVAL_CONFIGS = [
    ("token-512-0", "token", 512, 0, 0.680, 0.321, 15_539),
    ("token-512-64", "token", 512, 64, 0.640, 0.334, 17_756),
    ("token-1024-0", "token", 1024, 0, 0.660, 0.371, 8_309),
    ("token-1024-64", "token", 1024, 64, 0.640, 0.315, 8_882),
    ("sentence-512-0", "sentence", 512, 0, 0.440, 0.216, 7_956),
]

WINNER_CASE_ID = "token-512-0"


def _import_results(db_url: str) -> int:
    """Create EvalSuite, EvalRun, and EvalResult records."""
    session_factory = make_session_factory(create_db_engine(db_url))

    with session_factory() as session:
        # Look up the source by slug.
        source = session.execute(
            select(Source).where(Source.slug == SOURCE_SLUG)
        ).scalar_one_or_none()

        if source is None:
            logger.error(
                "source '%s' not found in catalog; run ingest_va_cpg.py first",
                SOURCE_SLUG,
            )
            return 1
        logger.info("found source: %s (id=%s)", source.slug, source.id)

        # Use the source's active physical index.
        physical_index = session.execute(
            select(PhysicalIndex)
            .where(PhysicalIndex.id == source.active_physical_index_id)
        ).scalar_one_or_none()

        if physical_index is None:
            logger.error(
                "no physical index found for source '%s'; run ingest_va_cpg.py first",
                SOURCE_SLUG,
            )
            return 1
        logger.info("found physical index: %s (location=%s)", physical_index.id, physical_index.location)

        # Check for an existing suite with the same slug to make this idempotent.
        existing_suite = session.execute(
            select(EvalSuite).where(
                EvalSuite.slug == SUITE_SLUG,
                EvalSuite.version_number == 1,
            )
        ).scalar_one_or_none()

        if existing_suite is not None:
            logger.warning(
                "EvalSuite '%s' v1 already exists (id=%s); skipping import",
                SUITE_SLUG,
                existing_suite.id,
            )
            print(f"EvalSuite '{SUITE_SLUG}' already exists. Nothing to do.")
            return 0

        # Create the EvalSuite.
        now = datetime.now(UTC)
        suite = EvalSuite(
            slug=SUITE_SLUG,
            name=SUITE_NAME,
            applies_to_family=EvalSuiteFamily.CLINICAL_DOCUMENT,
            version_number=1,
            description=(
                "Chunking strategy evaluation using AutoRAG across five "
                "configurations: Token and Sentence splitting at 512 and 1024 "
                "token sizes with 0 and 64 token overlap. Evaluated against "
                "the VA CPG clinical guidelines corpus with PubMedBERT embeddings."
            ),
            metric_set={
                "recall_at_5": {
                    "description": "Hit rate at k=5 (fraction of queries where a relevant document appears in top 5)",
                    "higher_is_better": True,
                },
                "mrr": {
                    "description": "Mean Reciprocal Rank (average of 1/rank of the first relevant result)",
                    "higher_is_better": True,
                },
            },
            created_by="script:import_eval_results",
        )
        session.add(suite)
        session.flush()  # Populate suite.id
        logger.info("created EvalSuite: %s (id=%s)", suite.slug, suite.id)

        # Create an EvalRun for the winning configuration.
        winner = next(c for c in EVAL_CONFIGS if c[0] == WINNER_CASE_ID)
        run = EvalRun(
            source_id=source.id,
            physical_index_id=physical_index.id,
            eval_suite_id=suite.id,
            eval_suite_version=suite.version_number,
            llm="none",
            rewrite_enabled=False,
            status=EvalRunStatus.COMPLETED,
            execution_backend=ExecutionBackend.NATIVE,
            scores={
                "recall_at_5": winner[4],
                "mrr": winner[5],
            },
            started_at=now,
            completed_at=now,
            triggered_by="script:import_eval_results",
            triggered_by_kind=TriggeredByKind.USER,
        )
        session.add(run)
        session.flush()  # Populate run.id
        logger.info("created EvalRun: %s (status=%s)", run.id, run.status)

        # Create EvalResult rows for each configuration.
        for case_id, chunker, chunk_size, overlap, hit_rate, mrr, chunk_count in EVAL_CONFIGS:
            result = EvalResult(
                eval_run_id=run.id,
                case_id=case_id,
                metrics={
                    "recall_at_5": hit_rate,
                    "mrr": mrr,
                },
                payload={
                    "chunker": chunker,
                    "chunk_size_tokens": chunk_size,
                    "overlap_tokens": overlap,
                    "chunk_count": chunk_count,
                    "embedding_model": EMBEDDING_MODEL,
                    "winner": case_id == WINNER_CASE_ID,
                },
            )
            session.add(result)
            logger.info("  added EvalResult: case_id=%s, recall@5=%.3f, mrr=%.3f", case_id, hit_rate, mrr)

        session.commit()
        logger.info("committed all records")

        # Capture values before session closes.
        source_id = source.id
        pi_location = physical_index.location
        pi_id = physical_index.id
        suite_slug = suite.slug
        suite_ver = suite.version_number
        suite_id = suite.id
        run_id = run.id
        run_status = run.status

    # Summary
    print()
    print("=" * 72)
    print("AutoRAG eval results imported")
    print("=" * 72)
    print(f"  Source               : {SOURCE_SLUG} ({source_id})")
    print(f"  Physical index       : {pi_location} ({pi_id})")
    print(f"  EvalSuite            : {suite_slug} v{suite_ver} ({suite_id})")
    print(f"  EvalRun              : {run_id} (status={run_status})")
    print(f"  EvalResults          : {len(EVAL_CONFIGS)} configurations")
    print()
    print("  Winning config       : Token-512-0")
    print(f"    recall@5           : {winner[4]:.3f}")
    print(f"    mrr                : {winner[5]:.3f}")
    print(f"    chunks             : {winner[6]:,}")
    print("=" * 72)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Import AutoRAG evaluation results into the catalog database."
    )
    parser.add_argument(
        "--db-url",
        default=DEFAULT_DB_URL,
        help=f"SQLAlchemy URL for the catalog database. Default: {DEFAULT_DB_URL}",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=args.log_level,
        format="%(asctime)s %(levelname)-5s %(name)s: %(message)s",
    )

    return _import_results(db_url=args.db_url)


if __name__ == "__main__":
    sys.exit(main())
