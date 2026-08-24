"""Auto-register eval results into the catalog eval register.

Called by __main__.py after a successful eval run. Writes eval_suite,
eval_run, and eval_result records following the same pattern as
scripts/import_v2_expanded_results.py.
"""

from __future__ import annotations

import json
import logging
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

logger = logging.getLogger("evalhub_runner.register")

SOURCE_SLUG = "va-cpg-clinical-guidelines"
INDEX_LOCATION = "idx_va_cpg_nomic_v1"
SUITE_SLUG = "va-cpg-answer-quality-evalhub"
SUITE_NAME = "VA CPG answer quality — EvalHub automated sweep"

METRIC_SET = {
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
}


def register_results(
    run_dir: Path,
    db_url: str,
    run_id: str,
    sweep_id: str,
) -> None:
    summary_path = run_dir / "summary.json"
    if not summary_path.exists():
        logger.error("summary.json not found in %s", run_dir)
        return

    summary = json.loads(summary_path.read_text())
    config = summary.get("config", {})
    session_factory = make_session_factory(create_db_engine(db_url))

    with session_factory() as session:
        source = session.execute(
            select(Source).where(Source.slug == SOURCE_SLUG)
        ).scalar_one_or_none()
        if source is None:
            logger.error("source '%s' not found", SOURCE_SLUG)
            return

        physical_index = session.execute(
            select(PhysicalIndex)
            .where(
                PhysicalIndex.location == INDEX_LOCATION,
                PhysicalIndex.source_id == source.id,
            )
            .order_by(PhysicalIndex.built_at.desc())
            .limit(1)
        ).scalar_one_or_none()
        if physical_index is None:
            logger.error(
                "no physical index '%s' for source '%s'",
                INDEX_LOCATION, SOURCE_SLUG,
            )
            return

        suite = session.execute(
            select(EvalSuite).where(EvalSuite.slug == SUITE_SLUG)
        ).scalar_one_or_none()
        if suite is None:
            suite = EvalSuite(
                slug=SUITE_SLUG,
                name=SUITE_NAME,
                applies_to_family=EvalSuiteFamily.CLINICAL_DOCUMENT,
                version_number=1,
                description=(
                    "Automated EvalHub sweep results for VA CPG source. "
                    "107-query dataset, Nomic v1.5 embeddings, 512/0 chunks."
                ),
                metric_set=METRIC_SET,
                created_by="evalhub",
            )
            session.add(suite)
            session.flush()
            logger.info("created EvalSuite: %s (id=%s)", suite.slug, suite.id)
        else:
            logger.info("using existing EvalSuite: %s (id=%s)", suite.slug, suite.id)

        now = datetime.now(UTC)

        for condition in ("raw", "rewrite"):
            cond_data = summary.get(condition)
            if cond_data is None:
                logger.warning("no '%s' data in summary.json, skipping", condition)
                continue

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
                execution_backend=ExecutionBackend.EVALHUB,
                scores=scores,
                started_at=now,
                completed_at=now,
                triggered_by=f"evalhub:{run_id}",
                triggered_by_kind=TriggeredByKind.SERVICE,
            )
            session.add(run)
            session.flush()

            payload = {
                "chunk_tokens": 512,
                "overlap_tokens": 0,
                "embedding_model": "nomic-ai/nomic-embed-text-v1.5",
                "table": INDEX_LOCATION,
                "condition": condition,
                "query_count": config.get("query_count", 107),
                "dataset_version": "v2",
                "sweep_id": sweep_id,
                "run_id": run_id,
                "refine_strategy": config.get("refine_strategy"),
                "refine_window": config.get("refine_window"),
            }
            ci_keys = {
                k: cond_data[f"{k}_ci"]
                for k in scores
                if f"{k}_ci" in cond_data
            }
            if ci_keys:
                payload["confidence_intervals"] = ci_keys

            result = EvalResult(
                eval_run_id=run.id,
                case_id=f"evalhub-{run_id}-{condition}",
                metrics=scores,
                payload=payload,
            )
            session.add(result)
            logger.info(
                "  %s: ctx_prec=%.3f  ans_rel=%.3f  faith=%.3f",
                condition,
                scores["context_precision"],
                scores["answer_relevancy"],
                scores["faithfulness"],
            )

        session.commit()
        logger.info("results committed to eval register")
