"""Import VA CPG Nomic v1.5 chunk sweep evaluation results into the catalog.

Records the results of the Nomic v1.5 chunking sweep (4 configurations:
256/0, 512/0, 512/64, 1024/0) as EvalSuite, EvalRun, and EvalResult rows
in the catalog database.  Retrieval metrics come from sweep_results.json;
Ragas answer-quality metrics come from per-config summary.json files where
available.

Usage:

    # With port-forward to the catalog DB already running on :5434
    python scripts/import_nomic_sweep_results.py

    # Or with a custom DB URL
    python scripts/import_nomic_sweep_results.py \
        --db-url postgresql+psycopg://user:pass@host:5432/db
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import UTC, datetime
from pathlib import Path

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

logger = logging.getLogger("import_nomic_sweep_results")

DEFAULT_DB_URL = "postgresql+psycopg://retrievalhub:retrievalhub@127.0.0.1:5434/retrievalhub"

SOURCE_SLUG = "va-cpg-clinical-guidelines"
SUITE_SLUG = "va-cpg-nomic-chunking-sweep"
SUITE_NAME = "VA CPG Nomic v1.5 chunking sweep"
EMBEDDING_MODEL = "nomic-ai/nomic-embed-text-v1.5"

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SWEEP_RESULTS_PATH = PROJECT_ROOT / "eval" / "va_cpg_chunking_sweep" / "sweep_results.json"

# Map from sweep config key to the Ragas summary.json path (relative to
# PROJECT_ROOT).  Configs without a Ragas run are omitted.
RAGAS_SUMMARY_PATHS: dict[str, Path] = {
    "512_0": PROJECT_ROOT / "eval" / "rewrite_lift" / "runs" / "embed-nomic-faithful" / "summary.json",
    "512_64": PROJECT_ROOT / "eval" / "rewrite_lift" / "runs" / "nomic-512-64" / "summary.json",
    "1024_0": PROJECT_ROOT / "eval" / "rewrite_lift" / "runs" / "nomic-1024-0" / "summary.json",
}

RAGAS_METRICS = ("context_precision", "answer_relevancy", "faithfulness")
RETRIEVAL_METRICS = ("hit_rate_at_5", "mrr_at_5", "mean_cosine_sim")


def _load_sweep_results() -> dict:
    """Load sweep_results.json from the eval directory."""
    with open(SWEEP_RESULTS_PATH) as f:
        return json.load(f)


def _load_ragas_summary(config_key: str) -> dict | None:
    """Load Ragas summary for a config, returning None if unavailable."""
    path = RAGAS_SUMMARY_PATHS.get(config_key)
    if path is None:
        return None
    if not path.exists():
        logger.warning(
            "Ragas summary not found for config %s at %s; skipping Ragas metrics",
            config_key,
            path,
        )
        return None
    with open(path) as f:
        return json.load(f)


def _build_scores(sweep_config: dict, ragas_summary: dict | None) -> dict:
    """Combine retrieval metrics and Ragas raw-condition metrics into one dict."""
    scores: dict[str, float] = {}
    for metric in RETRIEVAL_METRICS:
        if metric in sweep_config:
            scores[metric] = sweep_config[metric]

    if ragas_summary is not None:
        raw = ragas_summary.get("raw", {})
        for metric in RAGAS_METRICS:
            if metric in raw:
                scores[metric] = raw[metric]

    return scores


def _case_id_from_key(config_key: str) -> str:
    """Convert sweep config key (e.g. '512_64') to a case_id ('nomic-512-64')."""
    return f"nomic-{config_key.replace('_', '-')}"


def _import_results(db_url: str) -> int:
    """Create EvalSuite, EvalRun, and EvalResult records."""
    sweep_data = _load_sweep_results()
    configs = sweep_data["results"]

    session_factory = make_session_factory(create_db_engine(db_url))

    with session_factory() as session:
        # Look up the source by slug.
        source = session.execute(
            select(Source).where(Source.slug == SOURCE_SLUG)
        ).scalar_one_or_none()

        if source is None:
            logger.error(
                "source '%s' not found in catalog; run ingestion first",
                SOURCE_SLUG,
            )
            return 1
        logger.info("found source: %s (id=%s)", source.slug, source.id)

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

        # Resolve PhysicalIndex for each config by matching location + source_id.
        # Some tables (e.g. idx_va_cpg_nomic_v1) have multiple PhysicalIndex
        # rows from successive ingestion runs; take the most recent.
        index_by_config: dict[str, PhysicalIndex] = {}
        for config_key, config_data in configs.items():
            table_name = config_data["table"]
            physical_index = session.execute(
                select(PhysicalIndex)
                .where(
                    PhysicalIndex.location == table_name,
                    PhysicalIndex.source_id == source.id,
                )
                .order_by(PhysicalIndex.built_at.desc())
                .limit(1)
            ).scalar_one_or_none()

            if physical_index is None:
                logger.error(
                    "no physical index with location='%s' for source '%s'; "
                    "ensure all sweep indexes are registered",
                    table_name,
                    SOURCE_SLUG,
                )
                return 1
            index_by_config[config_key] = physical_index
            logger.info(
                "  config %s -> physical index %s (location=%s)",
                config_key,
                physical_index.id,
                physical_index.location,
            )

        # Determine the winner: whichever config maps to the active index.
        active_index_id = source.active_physical_index_id
        winner_key: str | None = None
        for config_key, pi in index_by_config.items():
            if pi.id == active_index_id:
                winner_key = config_key
                break

        if winner_key is None:
            logger.warning(
                "no config maps to the active physical index (%s); "
                "no config will be marked as winner",
                active_index_id,
            )

        # Create the EvalSuite.
        now = datetime.now(UTC)
        suite = EvalSuite(
            slug=SUITE_SLUG,
            name=SUITE_NAME,
            applies_to_family=EvalSuiteFamily.CLINICAL_DOCUMENT,
            version_number=1,
            description=(
                "Chunking sweep over 4 configurations (256/0, 512/0, 512/64, "
                "1024/0) using Nomic v1.5 embeddings, combining retrieval "
                "metrics (hit_rate, MRR, cosine_sim) and Ragas answer-quality "
                "scoring (context_precision, answer_relevancy, faithfulness)."
            ),
            metric_set={
                "hit_rate_at_5": {
                    "description": "Hit rate at k=5 (fraction of queries with a relevant result in top 5)",
                    "higher_is_better": True,
                },
                "mrr_at_5": {
                    "description": "Mean Reciprocal Rank at k=5",
                    "higher_is_better": True,
                },
                "mean_cosine_sim": {
                    "description": "Mean cosine similarity of top-5 retrieved chunks",
                    "higher_is_better": True,
                },
                "context_precision": {
                    "description": "Ragas context precision (relevant chunks ranked higher)",
                    "higher_is_better": True,
                },
                "answer_relevancy": {
                    "description": "Ragas answer relevancy (answer addresses the question)",
                    "higher_is_better": True,
                },
                "faithfulness": {
                    "description": "Ragas faithfulness (answer grounded in retrieved context)",
                    "higher_is_better": True,
                },
            },
            created_by="script:import_nomic_sweep_results",
        )
        session.add(suite)
        session.flush()
        logger.info("created EvalSuite: %s (id=%s)", suite.slug, suite.id)

        # Create one EvalRun + EvalResult per config.
        run_ids: list[str] = []
        for config_key, config_data in configs.items():
            ragas_summary = _load_ragas_summary(config_key)
            scores = _build_scores(config_data, ragas_summary)
            has_ragas = ragas_summary is not None
            case_id = _case_id_from_key(config_key)

            run = EvalRun(
                source_id=source.id,
                physical_index_id=index_by_config[config_key].id,
                eval_suite_id=suite.id,
                eval_suite_version=1,
                llm="gpt-oss-120b" if has_ragas else "none",
                rewrite_enabled=False,
                status=EvalRunStatus.COMPLETED,
                execution_backend=ExecutionBackend.NATIVE,
                scores=scores,
                started_at=now,
                completed_at=now,
                triggered_by="script:import_nomic_sweep_results",
                triggered_by_kind=TriggeredByKind.USER,
            )
            session.add(run)
            session.flush()
            run_ids.append(run.id)
            logger.info(
                "created EvalRun: %s (config=%s, llm=%s)",
                run.id,
                config_key,
                run.llm,
            )

            is_winner = config_key == winner_key
            result = EvalResult(
                eval_run_id=run.id,
                case_id=case_id,
                metrics=scores,
                payload={
                    "chunk_tokens": config_data["chunk_tokens"],
                    "overlap_tokens": config_data["overlap"],
                    "chunk_count": config_data["chunk_count"],
                    "embedding_model": EMBEDDING_MODEL,
                    "table": config_data["table"],
                    "winner": is_winner,
                },
            )
            session.add(result)
            logger.info(
                "  added EvalResult: case_id=%s, winner=%s",
                case_id,
                is_winner,
            )

        session.commit()
        logger.info("committed all records")

        # Capture values before session closes.
        source_id = source.id
        suite_id = suite.id

    # Summary.
    print()
    print("=" * 72)
    print("Nomic v1.5 chunk sweep results imported")
    print("=" * 72)
    print(f"  Source               : {SOURCE_SLUG} ({source_id})")
    print(f"  EvalSuite            : {SUITE_SLUG} v1 ({suite_id})")
    print(f"  EvalRuns             : {len(run_ids)}")
    print(f"  EvalResults          : {len(configs)} configurations")
    if winner_key is not None:
        winner_case = _case_id_from_key(winner_key)
        print(f"  Winner (active idx)  : {winner_case}")
    else:
        print("  Winner (active idx)  : none matched")
    print()
    for config_key, config_data in configs.items():
        case_id = _case_id_from_key(config_key)
        marker = " *" if config_key == winner_key else ""
        print(
            f"  {case_id:<20s}  hit@5={config_data['hit_rate_at_5']:.3f}  "
            f"mrr@5={config_data['mrr_at_5']:.4f}  "
            f"cos={config_data['mean_cosine_sim']:.4f}  "
            f"chunks={config_data['chunk_count']:>6,}{marker}"
        )
    print("=" * 72)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Import VA CPG Nomic v1.5 chunk sweep results into the catalog database."
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
