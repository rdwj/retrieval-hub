"""Import VA CPG v2 expanded eval results into the catalog eval register.

Records the 107-query expanded evaluation (Phase 5) as a new EvalSuite with
bootstrap confidence intervals. Single configuration: 512/0 with Nomic v1.5.

Usage:
    python scripts/import_v2_expanded_results.py
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

logger = logging.getLogger("import_v2_expanded_results")

DEFAULT_DB_URL = "postgresql+psycopg://retrievalhub:retrievalhub@127.0.0.1:5434/retrievalhub"
SOURCE_SLUG = "va-cpg-clinical-guidelines"
SUITE_SLUG = "va-cpg-nomic-answer-quality-v2"
SUITE_NAME = "VA CPG answer quality — expanded 107-query dataset"
ACTIVE_TABLE = "idx_va_cpg_nomic_v1"

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SUMMARY_PATH = PROJECT_ROOT / "eval" / "rewrite_lift" / "runs" / "v2-512-0-expanded" / "summary.json"


def _import_results(db_url: str) -> int:
    summary = json.loads(SUMMARY_PATH.read_text())
    session_factory = make_session_factory(create_db_engine(db_url))

    with session_factory() as session:
        source = session.execute(
            select(Source).where(Source.slug == SOURCE_SLUG)
        ).scalar_one_or_none()
        if source is None:
            logger.error("source '%s' not found", SOURCE_SLUG)
            return 1

        existing = session.execute(
            select(EvalSuite).where(
                EvalSuite.slug == SUITE_SLUG,
                EvalSuite.version_number == 1,
            )
        ).scalar_one_or_none()
        if existing is not None:
            logger.warning("suite '%s' v1 already exists (id=%s); skipping", SUITE_SLUG, existing.id)
            print(f"EvalSuite '{SUITE_SLUG}' already exists. Nothing to do.")
            return 0

        physical_index = session.execute(
            select(PhysicalIndex)
            .where(
                PhysicalIndex.location == ACTIVE_TABLE,
                PhysicalIndex.source_id == source.id,
            )
            .order_by(PhysicalIndex.built_at.desc())
            .limit(1)
        ).scalar_one_or_none()
        if physical_index is None:
            logger.error("no physical index '%s' for source '%s'", ACTIVE_TABLE, SOURCE_SLUG)
            return 1

        now = datetime.now(UTC)
        suite = EvalSuite(
            slug=SUITE_SLUG,
            name=SUITE_NAME,
            applies_to_family=EvalSuiteFamily.CLINICAL_DOCUMENT,
            version_number=1,
            description=(
                "Expanded 107-query evaluation (50 hand-crafted + 57 LLM-generated) "
                "covering all 26 VA/DoD CPGs. 512/0 chunk config with Nomic v1.5 "
                "embeddings. Includes 95% bootstrap confidence intervals on all metrics."
            ),
            metric_set={
                "context_precision": {
                    "description": "Ragas context precision",
                    "higher_is_better": True,
                },
                "answer_relevancy": {
                    "description": "Ragas answer relevancy",
                    "higher_is_better": True,
                },
                "faithfulness": {
                    "description": "Ragas faithfulness",
                    "higher_is_better": True,
                },
            },
            created_by="script:import_v2_expanded_results",
        )
        session.add(suite)
        session.flush()
        logger.info("created EvalSuite: %s (id=%s)", suite.slug, suite.id)

        for condition in ("raw", "rewrite"):
            cond_data = summary[condition]
            scores = {
                "context_precision": cond_data["context_precision"],
                "answer_relevancy": cond_data["answer_relevancy"],
                "faithfulness": cond_data["faithfulness"],
            }

            run = EvalRun(
                source_id=source.id,
                physical_index_id=physical_index.id,
                eval_suite_id=suite.id,
                eval_suite_version=1,
                llm="gpt-oss-120b",
                rewrite_enabled=(condition == "rewrite"),
                status=EvalRunStatus.COMPLETED,
                execution_backend=ExecutionBackend.NATIVE,
                scores=scores,
                started_at=now,
                completed_at=now,
                triggered_by="script:import_v2_expanded_results",
                triggered_by_kind=TriggeredByKind.USER,
            )
            session.add(run)
            session.flush()

            result = EvalResult(
                eval_run_id=run.id,
                case_id=f"nomic-512-0-v2-{condition}",
                metrics=scores,
                payload={
                    "chunk_tokens": 512,
                    "overlap_tokens": 0,
                    "embedding_model": "nomic-ai/nomic-embed-text-v1.5",
                    "table": ACTIVE_TABLE,
                    "condition": condition,
                    "query_count": summary["config"]["query_count"],
                    "dataset_version": "v2",
                    "confidence_intervals": {
                        k: cond_data[f"{k}_ci"]
                        for k in scores
                        if f"{k}_ci" in cond_data
                    },
                },
            )
            session.add(result)
            logger.info(
                "  %s condition: ctx_prec=%.3f  ans_rel=%.3f  faith=%.3f",
                condition,
                scores["context_precision"],
                scores["answer_relevancy"],
                scores["faithfulness"],
            )

        session.commit()
        logger.info("committed all records")

        source_id = source.id
        suite_id = suite.id

    print()
    print("=" * 72)
    print("V2 expanded eval results imported")
    print("=" * 72)
    print(f"  Source    : {SOURCE_SLUG} ({source_id})")
    print(f"  Suite     : {SUITE_SLUG} v1 ({suite_id})")
    print(f"  Index     : {ACTIVE_TABLE}")
    print(f"  Queries   : {summary['config']['query_count']}")
    print()
    for cond in ("raw", "rewrite"):
        d = summary[cond]
        print(f"  {cond.upper():>7s}  ctx_prec={d['context_precision']:.3f} [{d['context_precision_ci'][0]:.3f}, {d['context_precision_ci'][1]:.3f}]")
        print(f"           ans_rel ={d['answer_relevancy']:.3f} [{d['answer_relevancy_ci'][0]:.3f}, {d['answer_relevancy_ci'][1]:.3f}]")
        print(f"           faith  ={d['faithfulness']:.3f} [{d['faithfulness_ci'][0]:.3f}, {d['faithfulness_ci'][1]:.3f}]")
        print()
    print("=" * 72)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db-url", default=DEFAULT_DB_URL)
    parser.add_argument("--log-level", default="INFO", choices=["DEBUG", "INFO", "WARNING", "ERROR"])
    args = parser.parse_args()
    logging.basicConfig(level=args.log_level, format="%(asctime)s %(levelname)-5s %(name)s: %(message)s")
    return _import_results(db_url=args.db_url)


if __name__ == "__main__":
    sys.exit(main())
