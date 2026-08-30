"""Self-serve source onboarding pipeline.

Takes raw data and a minimal config, ingests the corpus, and registers it
as a CURATED source. Optionally runs a parameter sweep with QA generation
and Ragas evaluation to select the best chunk configuration.

Quick onboarding (minutes)::

    python scripts/onboard_source.py \\
        --slug my-source \\
        --data-dir ./my-data/ \\
        --family document \\
        --name "My Source" \\
        --description "Short description" \\
        --skip-eval

Full eval sweep (hours — requires LLM endpoint for QA gen + scoring)::

    python scripts/onboard_source.py \\
        --slug my-source \\
        --data-dir ./my-data/ \\
        --family document \\
        --name "My Source" \\
        --description "Short description" \\
        --num-qa-pairs 20

The full sweep ingests 3 chunk configs (256/0, 512/0, 512/64), generates
QA pairs from the source documents, runs Ragas evaluation (context
precision, answer relevancy, faithfulness) on each config, selects the
winner, and drops the losers. This process is thorough but expensive:
it requires an LLM endpoint for QA generation and Ragas scoring, and
each config's eval takes 1-3 hours depending on corpus size and LLM
throughput.

For most new datasets, --skip-eval is recommended. Use the full sweep
when establishing a quality baseline for a high-value source or when
comparing chunk strategies.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import re
import sys
from pathlib import Path
from typing import Any

_SCRIPTS_DIR = str(Path(__file__).resolve().parent)
if _SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, _SCRIPTS_DIR)

logger = logging.getLogger(__name__)

_SLUG_RE = re.compile(r"^[a-z0-9]([a-z0-9-]*[a-z0-9])?$")
_CONSECUTIVE_HYPHENS_RE = re.compile(r"--")

SUPPORTED_FAMILIES = {
    "document",
    "clinical_document",
    "technical_document",
    "process",
    "code",
}

DEFAULT_DB_URL = "postgresql+psycopg://retrievalhub:retrievalhub@127.0.0.1:5434/retrievalhub"
DEFAULT_VECTORS_DB_URL = (
    "postgresql+psycopg://retrievalhub:retrievalhub@127.0.0.1:5433/retrievalhub_vectors"
)
DEFAULT_EMBEDDING_MODEL = "nomic-ai/nomic-embed-text-v1.5"

DEFAULT_LLM_URL = (
    "https://gpt-oss-120b-direct-gpt-oss-120b-model.apps."
    "cluster-z9hbt.z9hbt.sandbox1495.opentlc.com/v1"
)
DEFAULT_LLM_MODEL = "/mnt/models"

CANDIDATE_CONFIGS = [
    {"chunk_tokens": 256, "overlap_tokens": 0},
    {"chunk_tokens": 512, "overlap_tokens": 0},
    {"chunk_tokens": 512, "overlap_tokens": 64},
]


def _validate_slug(slug: str) -> None:
    if not slug:
        print("Error: --slug must not be empty", file=sys.stderr)
        sys.exit(1)
    if not _SLUG_RE.match(slug):
        print(
            f"Error: invalid slug {slug!r}: must contain only lowercase "
            "letters, digits, and hyphens; must not start or end with a hyphen",
            file=sys.stderr,
        )
        sys.exit(1)
    if _CONSECUTIVE_HYPHENS_RE.search(slug):
        print(
            f"Error: invalid slug {slug!r}: must not contain consecutive hyphens",
            file=sys.stderr,
        )
        sys.exit(1)


def _discover_documents(data_dir: Path) -> dict[str, int]:
    """Walk data_dir and report file counts by extension."""
    counts: dict[str, int] = {}
    for ext in (".md", ".txt", ".html", ".htm", ".pdf", ".json", ".py"):
        files = list(data_dir.rglob(f"*{ext}"))
        if files:
            counts[ext] = len(files)
    return counts


def _table_suffix(config: dict[str, int]) -> str:
    return f"{config['chunk_tokens']}_{config['overlap_tokens']}"


def _run_ingestion(
    args: argparse.Namespace,
    config: dict[str, int],
) -> dict[str, Any]:
    """Run a single ingestion pass with the given chunk config."""
    from retrieval_hub.ingestion.pipeline import ingest

    suffix = _table_suffix(config)
    logger.info(
        "Ingesting %s with chunk_tokens=%d overlap=%d (table suffix: %s)",
        args.slug, config["chunk_tokens"], config["overlap_tokens"], suffix,
    )

    result = ingest(
        data_dir=Path(args.data_dir),
        slug=args.slug,
        name=args.name,
        family=args.family,
        description_short=args.description,
        description_long=getattr(args, "description_long", args.description),
        owner_team=args.owner_team,
        owner_contacts=[],
        db_url=args.db_url,
        vectors_db_url=args.vectors_db_url,
        chunk_tokens=config["chunk_tokens"],
        overlap_tokens=config["overlap_tokens"],
        embedding_model=args.embedding_model,
        embedding_endpoint=getattr(args, "embedding_endpoint", None),
        table_suffix=suffix,
    )

    return {
        "config": config,
        "suffix": suffix,
        "source_id": result.source_id,
        "physical_index_id": result.physical_index_id,
        "created": result.created_source,
    }


def _run_qa_generation(args: argparse.Namespace) -> Path:
    """Generate QA pairs for the source. Returns path to the QA dataset."""
    output_dir = Path(f"eval/{args.slug}")
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / "qa_generated.json"

    if output_path.exists() and not args.force:
        logger.info("QA pairs already exist at %s, skipping generation", output_path)
        return output_path

    from generate_qa_pairs import generate_pairs

    generate_pairs(
        data_dir=Path(args.data_dir),
        source_slug=args.slug,
        source_name=args.name,
        family=args.family,
        num_pairs=args.num_qa_pairs,
        llm_url=args.llm_url,
        llm_model=args.llm_model,
        output_path=output_path,
        dry_run=False,
    )
    return output_path


async def _run_eval(
    args: argparse.Namespace,
    config: dict[str, int],
    qa_dataset: Path,
) -> dict[str, Any] | None:
    """Run eval for a single chunk config. Returns summary dict or None."""
    from eval_answer_quality import _run as eval_run
    from eval_answer_quality import build_eval_args

    suffix = _table_suffix(config)
    run_dir = Path(f"eval/{args.slug}/runs/{suffix}")

    summary_path = run_dir / "summary.json"
    if summary_path.exists() and not args.force:
        logger.info("Eval already complete for %s, loading summary", suffix)
        return json.loads(summary_path.read_text())

    eval_args = build_eval_args(
        source_slug=args.slug,
        qa_dataset=str(qa_dataset),
        db_url=args.db_url,
        vectors_db_url=args.vectors_db_url,
        scoring_llm_url=args.llm_url,
        scoring_llm_model=args.llm_model,
        answer_llm_url=getattr(args, "answer_llm_url", args.llm_url),
        answer_llm_model=getattr(args, "answer_llm_model", args.llm_model),
        run_dir=str(run_dir),
        max_workers=2,
        score_batch_size=10,
        force=args.force,
    )

    await eval_run(eval_args)

    if summary_path.exists():
        return json.loads(summary_path.read_text())
    logger.warning("Eval completed but no summary.json found at %s", summary_path)
    return None


def _select_winner(
    results: list[tuple[dict[str, int], dict[str, Any]]],
) -> tuple[dict[str, int], dict[str, Any]]:
    """Select the best chunk config based on eval metrics.

    Primary metric: answer_relevancy (from raw retrieval, no rewrite).
    Secondary metric: faithfulness.
    """
    scored = []
    for config, summary in results:
        raw = summary.get("raw", {})
        relevancy = raw.get("answer_relevancy", 0.0)
        faithfulness = raw.get("faithfulness", 0.0)
        scored.append((relevancy, faithfulness, config, summary))

    scored.sort(key=lambda x: (x[0], x[1]), reverse=True)
    winner = scored[0]
    return winner[2], winner[3]


def _promote_winner(
    args: argparse.Namespace,
    winner_config: dict[str, int],
    all_configs: list[dict[str, int]],
) -> None:
    """Repoint the source to the winning index and drop losers."""
    from retrieval_hub.db import create_db_engine, make_session_factory, session_scope
    from retrieval_hub.ingestion.write import drop_table
    from retrieval_hub.models import PhysicalIndex, Source

    winner_suffix = _table_suffix(winner_config)
    winner_table = f"idx_{args.slug.replace('-', '_')}_{winner_suffix}"

    engine = create_db_engine(args.db_url)
    factory = make_session_factory(engine)
    with session_scope(factory) as session:
        source = session.query(Source).filter(Source.slug == args.slug).one()
        pi = (
            session.query(PhysicalIndex)
            .filter(PhysicalIndex.location == winner_table)
            .one_or_none()
        )
        if pi:
            source.active_physical_index_id = pi.id
            logger.info("Promoted index %s for source %s", winner_table, args.slug)

    for config in all_configs:
        if config == winner_config:
            continue
        loser_suffix = _table_suffix(config)
        loser_table = f"idx_{args.slug.replace('-', '_')}_{loser_suffix}"
        try:
            drop_table(args.vectors_db_url, loser_table)
            logger.info("Dropped losing index table %s", loser_table)
        except Exception:
            logger.warning("Could not drop table %s", loser_table, exc_info=True)


def _print_report(
    winner_config: dict[str, int],
    winner_summary: dict[str, Any],
    all_results: list[tuple[dict[str, int], dict[str, Any]]],
    slug: str,
) -> None:
    """Print a human-readable summary of the onboarding results."""
    print("\n" + "=" * 60)
    print(f"  Onboarding Complete: {slug}")
    print("=" * 60)

    print("\n  Candidate results:")
    print(f"  {'Config':<20} {'Relevancy':>10} {'Faithfulness':>12} {'Precision':>10}")
    print(f"  {'-' * 20} {'-' * 10} {'-' * 12} {'-' * 10}")

    for config, summary in all_results:
        raw = summary.get("raw", {})
        marker = " *" if config == winner_config else ""
        label = f"{config['chunk_tokens']}/{config['overlap_tokens']}"
        print(
            f"  {label:<20} "
            f"{raw.get('answer_relevancy', 0):.3f}{'':<5} "
            f"{raw.get('faithfulness', 0):.3f}{'':<7} "
            f"{raw.get('context_precision', 0):.3f}{'':<5}"
            f"{marker}"
        )

    print(f"\n  Winner: {winner_config['chunk_tokens']} tokens / "
          f"{winner_config['overlap_tokens']} overlap")
    print(f"  Source is now CURATED and queryable as '{slug}'")
    print("=" * 60 + "\n")


async def run(args: argparse.Namespace) -> None:
    """Execute the full onboarding pipeline."""
    # Step 1: Validate
    _validate_slug(args.slug)
    data_dir = Path(args.data_dir)
    if not data_dir.is_dir():
        print(f"Error: --data-dir {data_dir} does not exist", file=sys.stderr)
        sys.exit(1)
    if args.family not in SUPPORTED_FAMILIES:
        print(
            f"Error: unsupported family {args.family!r}. "
            f"Supported: {sorted(SUPPORTED_FAMILIES)}",
            file=sys.stderr,
        )
        sys.exit(1)

    # Step 2: Discover documents
    counts = _discover_documents(data_dir)
    if not counts:
        print(f"Error: no supported files found in {data_dir}", file=sys.stderr)
        sys.exit(1)
    total = sum(counts.values())
    print(f"Found {total} files in {data_dir}:")
    for ext, count in sorted(counts.items()):
        print(f"  {ext}: {count}")

    if args.dry_run:
        if args.skip_eval:
            print("\n[dry-run] Would ingest with default config (512/0)")
        else:
            print("\n[dry-run] Would run ingestion with configs:")
            for config in CANDIDATE_CONFIGS:
                print(f"  chunk_tokens={config['chunk_tokens']} "
                      f"overlap={config['overlap_tokens']}")
            print(f"\n[dry-run] Would generate {args.num_qa_pairs} QA pairs")
            print("[dry-run] Would run eval on each config and select winner")
        return

    # -- Fast path: skip-eval mode --
    if args.skip_eval:
        default_config = {"chunk_tokens": 512, "overlap_tokens": 0}
        print(f"\nIngesting {args.slug} (skip-eval, config 512/0)...")
        result = _run_ingestion(args, default_config)
        print(f"  Ingested (source_id={result['source_id'][:8]}...)")
        print(f"\n  Source is now CURATED and queryable as '{args.slug}'")
        print("  (No eval baseline — run without --skip-eval for quality metrics)")
        return

    # -- Full eval sweep --
    # Step 3: Run ingestion with candidate configs
    print(f"\nIngesting {args.slug} with {len(CANDIDATE_CONFIGS)} candidate configs...")
    ingestion_results = []
    for config in CANDIDATE_CONFIGS:
        result = _run_ingestion(args, config)
        ingestion_results.append(result)
        print(f"  {_table_suffix(config)}: ingested "
              f"(source_id={result['source_id'][:8]}...)")

    # Step 4: Generate QA pairs
    print(f"\nGenerating {args.num_qa_pairs} QA pairs...")
    qa_path = _run_qa_generation(args)
    qa_data = json.loads(qa_path.read_text())
    qa_count = len(qa_data.get("questions", []))
    print(f"  Generated {qa_count} QA pairs at {qa_path}")

    # Step 5: Run eval on each candidate
    print(f"\nRunning eval on {len(CANDIDATE_CONFIGS)} configs...")
    eval_results: list[tuple[dict[str, int], dict[str, Any]]] = []
    for config in CANDIDATE_CONFIGS:
        print(f"  Evaluating {_table_suffix(config)}...")
        summary = await _run_eval(args, config, qa_path)
        if summary:
            eval_results.append((config, summary))
        else:
            print(f"  Warning: no eval results for {_table_suffix(config)}")

    if not eval_results:
        print("Error: no eval results produced", file=sys.stderr)
        sys.exit(1)

    # Step 6: Select winner
    winner_config, winner_summary = _select_winner(eval_results)

    # Step 7: Promote winner
    _promote_winner(args, winner_config, CANDIDATE_CONFIGS)

    # Step 8: Report
    _print_report(winner_config, winner_summary, eval_results, args.slug)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Self-serve source onboarding pipeline",
    )
    parser.add_argument("--slug", required=True, help="URL-safe source identifier")
    parser.add_argument("--data-dir", required=True, help="Directory containing source data")
    parser.add_argument("--family", default="document", help="Source family")
    parser.add_argument("--name", default=None, help="Human-readable source name")
    parser.add_argument("--description", default="", help="Short source description")
    parser.add_argument("--description-long", default=None, help="Detailed description")
    parser.add_argument("--owner-team", default="platform", help="Owning team")
    parser.add_argument(
        "--db-url", default=DEFAULT_DB_URL, help="Catalog database URL",
    )
    parser.add_argument(
        "--vectors-db-url", default=DEFAULT_VECTORS_DB_URL, help="pgvector database URL",
    )
    parser.add_argument(
        "--embedding-model", default=DEFAULT_EMBEDDING_MODEL, help="Embedding model name",
    )
    parser.add_argument("--embedding-endpoint", default=None, help="Remote embedding endpoint")
    parser.add_argument("--num-qa-pairs", type=int, default=20, help="QA pairs to generate")
    parser.add_argument("--llm-url", default=DEFAULT_LLM_URL, help="LLM endpoint URL")
    parser.add_argument("--llm-model", default=DEFAULT_LLM_MODEL, help="LLM model name")
    parser.add_argument("--answer-llm-url", default=None, help="Answer LLM URL (default: --llm-url)")
    parser.add_argument("--answer-llm-model", default=None, help="Answer LLM model")
    parser.add_argument("--skip-eval", action="store_true",
                        help="Ingest with default config (512/0) only, skip QA gen and eval")
    parser.add_argument("--force", action="store_true", help="Force re-run all stages")
    parser.add_argument("--dry-run", action="store_true", help="Show plan without executing")
    parser.add_argument("--log-level", default="INFO", help="Log level")

    args = parser.parse_args()

    if args.name is None:
        args.name = args.slug.replace("-", " ").title()
    if args.answer_llm_url is None:
        args.answer_llm_url = args.llm_url
    if args.answer_llm_model is None:
        args.answer_llm_model = args.llm_model

    logging.basicConfig(
        level=getattr(logging, args.log_level.upper()),
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )

    asyncio.run(run(args))


if __name__ == "__main__":
    main()
