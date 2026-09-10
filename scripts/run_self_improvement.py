"""Run the ontology self-improvement pipeline.

Orchestrates: benchmark run -> evaluate mapping quality -> adjust authority
scores -> doctor validation.  Can point to an existing benchmark run or
trigger a fresh one.

Usage::

    # Dry-run against the latest benchmark results:
    python scripts/run_self_improvement.py --benchmark-dir eval/ontology_benchmark/runs/20260910-145406 --dry-run

    # Full run (benchmark + score adjustment):
    python scripts/run_self_improvement.py --vectors-db-url postgresql+psycopg://...
"""

from __future__ import annotations

import argparse
import json
import logging
import subprocess
import sys
from dataclasses import asdict
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from retrieval_hub.ontology.doctor import check_eval_findings
from retrieval_hub.ontology.self_improve import (
    ScoreAdjustment,
    adjust_authority_scores,
    apply_adjustments,
    evaluate_mapping_quality,
)

logger = logging.getLogger(__name__)

DEFAULT_DB_URL = "postgresql+psycopg://retrievalhub:retrievalhub@127.0.0.1:5434/retrievalhub"
BENCHMARK_SCRIPT = Path(__file__).parent / "eval_ontology_benchmark.py"


def _find_latest_run() -> Path | None:
    runs_dir = Path(__file__).resolve().parent.parent / "eval/ontology_benchmark/runs"
    if not runs_dir.is_dir():
        return None
    runs = sorted(runs_dir.iterdir(), reverse=True)
    for d in runs:
        if (d / "summary.json").exists():
            return d
    return None


def _run_benchmark(db_url: str, vectors_db_url: str | None) -> Path | None:
    cmd = [sys.executable, str(BENCHMARK_SCRIPT), "--db-url", db_url]
    if vectors_db_url:
        cmd.extend(["--vectors-db-url", vectors_db_url])
    logger.info("Running benchmark: %s", " ".join(cmd))
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        logger.error("Benchmark failed:\n%s", result.stderr)
        return None
    return _find_latest_run()


def _print_findings(findings: list) -> None:
    by_cat: dict[str, int] = {}
    for f in findings:
        by_cat[f.category] = by_cat.get(f.category, 0) + 1
    print(f"\nFindings: {len(findings)} total")
    for cat, count in sorted(by_cat.items()):
        print(f"  {cat}: {count}")


def _print_adjustments(adjustments: list[ScoreAdjustment]) -> None:
    if not adjustments:
        print("\nNo authority score adjustments needed.")
        return
    print(f"\nAuthority Score Adjustments: {len(adjustments)}")
    print(f"  {'Mapping':<50} {'Old':>6}  {'New':>6}  Reason")
    print(f"  {'-'*50} {'-'*6}  {'-'*6}  {'-'*30}")
    for adj in adjustments:
        label = f"{adj.canonical_name}/{adj.source_slug}"
        print(f"  {label:<50} {adj.old_score:>6.3f}  {adj.new_score:>6.3f}  {adj.reason}")


def _print_doctor_findings(doctor_results: list[dict]) -> None:
    if not doctor_results:
        print("\nDoctor: no eval-related findings.")
        return
    warn_count = sum(1 for r in doctor_results if r.get("severity") == "WARN")
    info_count = len(doctor_results) - warn_count
    print(f"\nDoctor Eval Findings: {warn_count} WARN, {info_count} INFO")
    for r in doctor_results:
        sev = r.get("severity", "?")
        print(f"  [{sev}] {r.get('check')}: {r.get('message')}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--db-url", default=DEFAULT_DB_URL,
        help="ORM database URL (default: %(default)s)",
    )
    parser.add_argument(
        "--vectors-db-url", default=None,
        help="Vectors database URL (for benchmark run)",
    )
    parser.add_argument(
        "--benchmark-dir", type=Path, default=None,
        help="Path to an existing benchmark run directory. "
             "If omitted and --skip-benchmark is not set, runs a fresh benchmark.",
    )
    parser.add_argument(
        "--skip-benchmark", action="store_true",
        help="Skip benchmark and use the latest existing run.",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Show findings and proposed adjustments without writing to DB.",
    )
    parser.add_argument(
        "--verbose", "-v", action="store_true",
        help="Enable debug logging.",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)-5s %(name)s: %(message)s",
    )

    # Resolve benchmark directory.
    bench_dir: Path | None = args.benchmark_dir
    if bench_dir is None:
        if args.skip_benchmark:
            bench_dir = _find_latest_run()
            if bench_dir is None:
                print("ERROR: No existing benchmark runs found.", file=sys.stderr)
                return 1
            print(f"Using latest benchmark run: {bench_dir}")
        else:
            print("Running ontology benchmark...")
            bench_dir = _run_benchmark(args.db_url, args.vectors_db_url)
            if bench_dir is None:
                print("ERROR: Benchmark run failed.", file=sys.stderr)
                return 1
            print(f"Benchmark completed: {bench_dir}")

    # Load benchmark summary.
    summary_path = bench_dir / "summary.json"
    if not summary_path.exists():
        print(f"ERROR: {summary_path} not found.", file=sys.stderr)
        return 1

    summary = json.loads(summary_path.read_text())
    per_mapping = summary.get("per_mapping_quality")
    if not per_mapping:
        print("ERROR: No per_mapping_quality data in summary.json.", file=sys.stderr)
        print("Re-run the benchmark with the latest eval_ontology_benchmark.py.", file=sys.stderr)
        return 1

    print(f"Loaded {len(per_mapping)} mapping quality entries from {summary_path}")

    # Evaluate and adjust.
    make_session = sessionmaker(bind=create_engine(args.db_url))
    with make_session() as session:
        findings = evaluate_mapping_quality(session, per_mapping)
        _print_findings(findings)

        adjustments = adjust_authority_scores(session, findings)
        _print_adjustments(adjustments)

        if adjustments and not args.dry_run:
            apply_adjustments(session, adjustments)
            print(f"\nApplied {len(adjustments)} score adjustments to database.")
        elif adjustments and args.dry_run:
            print("\n[DRY RUN] No changes written to database.")

        # Doctor validation on flagged findings.
        findings_data = [asdict(f) for f in findings if f.category != "healthy"]
        doctor_results = check_eval_findings(session, eval_findings=findings_data)
        _print_doctor_findings(doctor_results)

        # Write findings to benchmark directory for later doctor use.
        findings_path = bench_dir / "eval_findings.json"
        findings_path.write_text(
            json.dumps(findings_data, indent=2, default=str) + "\n",
        )
        print(f"\nFindings written to {findings_path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
