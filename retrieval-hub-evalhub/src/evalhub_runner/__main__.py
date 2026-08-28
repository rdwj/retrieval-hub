"""EvalHub runner — container entry point for cluster-based eval Jobs.

Reads EVALHUB_* environment variables, builds an argparse Namespace
compatible with eval_answer_quality._run(), executes the eval pipeline,
then auto-registers results into the catalog eval register.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys
from pathlib import Path

logger = logging.getLogger("evalhub_runner")

LLM_BASE = "http://gpt-oss-120b-direct.gpt-oss-120b-model.svc:8080"
DB_HOST = "retrieval-hub-pg:5432"

DEFAULTS = {
    "db_url": f"postgresql+psycopg://retrievalhub:retrievalhub@{DB_HOST}/retrievalhub",
    "vectors_db_url": f"postgresql+psycopg://retrievalhub:retrievalhub@{DB_HOST}/retrievalhub_vectors",
    "llm_url": LLM_BASE,
    "llm_model": "/mnt/models",
    "refine_strategy": "",
    "refine_window": "2",
    "qa_dataset": "eval/qa_dataset_v2.json",
    "query_count": "0",
    "max_workers": "2",
    "score_batch_size": "10",
    "source_slug": "va-cpg-clinical-guidelines",
    "run_id": "",
    "sweep_id": "manual",
    "force": "false",
    "log_level": "INFO",
}


def _env(name: str) -> str:
    return os.environ.get(f"EVALHUB_{name.upper()}", DEFAULTS.get(name.lower(), ""))


def _build_args() -> argparse.Namespace:
    llm_url = _env("llm_url")
    llm_model = _env("llm_model")
    refine = _env("refine_strategy")
    run_id = _env("run_id")

    run_dir = f"runs/{run_id}" if run_id else None

    return argparse.Namespace(
        source_slug=_env("source_slug"),
        db_url=_env("db_url"),
        vectors_db_url=_env("vectors_db_url"),
        rewriter_llm_url=f"{llm_url}/v1/chat/completions",
        rewriter_llm_model=llm_model,
        answer_llm_url=f"{llm_url}/v1/chat/completions",
        answer_llm_model=llm_model,
        scoring_llm_url=f"{llm_url}/v1",
        scoring_llm_model=llm_model,
        refine_strategy=refine if refine else None,
        refine_window=int(_env("refine_window")),
        qa_dataset=_env("qa_dataset"),
        query_count=int(_env("query_count")),
        run_dir=run_dir,
        max_workers=int(_env("max_workers")),
        score_batch_size=int(_env("score_batch_size")),
        force=_env("force").lower() in ("true", "1", "yes"),
        log_level=_env("log_level"),
    )


def main() -> int:
    args = _build_args()

    logging.basicConfig(
        level=args.log_level,
        format="%(asctime)s %(levelname)-5s %(name)s: %(message)s",
    )

    run_id = _env("run_id") or "auto"
    sweep_id = _env("sweep_id")
    logger.info("EvalHub runner starting: run_id=%s sweep_id=%s", run_id, sweep_id)
    logger.info(
        "refine_strategy=%s refine_window=%s query_count=%s",
        args.refine_strategy, args.refine_window, args.query_count,
    )

    # eval_answer_quality is on PYTHONPATH via the container's ENV directive
    import eval_answer_quality

    # Patch the rewriter's default template path to the container's CWD copy.
    # The installed package resolves it relative to site-packages, which
    # doesn't contain the prompts directory.
    import retrieval_hub.rewriter.service as _rw_svc
    _rw_svc._DEFAULT_TEMPLATE_PATH = Path("prompts/rewriter-shared-core.yaml")

    rc = asyncio.run(eval_answer_quality._run(args))
    if rc != 0:
        logger.error("eval pipeline exited with code %d", rc)
        return rc

    # Determine the actual run_dir used (may have been auto-generated)
    if args.run_dir:
        run_dir_path = Path(args.run_dir)
    else:
        # Re-derive: the eval script uses DEFAULT_RUN_DIR / fingerprint
        # but we can find it from the most recent config.json
        candidates = sorted(
            Path(eval_answer_quality.DEFAULT_RUN_DIR).glob("*/config.json"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        if candidates:
            run_dir_path = candidates[0].parent
        else:
            logger.error("could not locate run directory after eval completed")
            return 1

    logger.info("registering results from %s", run_dir_path)
    from evalhub_runner.register import register_results

    register_results(
        run_dir=run_dir_path,
        db_url=args.db_url,
        run_id=run_id,
        sweep_id=sweep_id,
    )

    logger.info("EvalHub runner complete")
    return 0


if __name__ == "__main__":
    sys.exit(main())
