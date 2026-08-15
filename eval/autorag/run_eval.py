#!/usr/bin/env python
"""Run AutoRAG chunking + retrieval evaluation.

Orchestrates a two-phase evaluation:
  1. Chunking sweep — tests Token/Sentence methods at various sizes and overlaps
  2. (Future) Retrieval + reranking evaluation against the best chunked corpora

Usage:
    python eval/autorag/run_eval.py
    python eval/autorag/run_eval.py --data-dir eval/autorag/data --project-dir eval/autorag/results
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd


def run_chunking(data_dir: Path, chunk_config: Path, project_dir: Path) -> None:
    """Run AutoRAG chunker with multiple configurations."""
    try:
        from autorag.chunker import Chunker
    except ImportError:
        print(
            "ERROR: AutoRAG is not installed. Run: pip install AutoRAG",
            file=sys.stderr,
        )
        sys.exit(1)

    parsed_path = data_dir / "parsed.parquet"
    if not parsed_path.exists():
        print(
            f"ERROR: {parsed_path} not found. Run prepare_data.py first.",
            file=sys.stderr,
        )
        sys.exit(1)

    chunk_dir = project_dir / "chunk"
    chunk_dir.mkdir(parents=True, exist_ok=True)

    print(f"Starting chunking sweep ...")
    print(f"  Parsed data: {parsed_path}")
    print(f"  Config:      {chunk_config}")
    print(f"  Output:      {chunk_dir}")

    chunker = Chunker.from_parquet(
        parsed_data_path=str(parsed_path),
        project_dir=str(chunk_dir),
    )
    chunker.start_chunking(str(chunk_config))

    # Print summary if available
    summary_path = chunk_dir / "summary.csv"
    if summary_path.exists():
        print("\nChunking results:")
        summary = pd.read_csv(summary_path)
        print(summary.to_string(index=False))
    else:
        print("\nChunking complete. Check output directory for results.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Run AutoRAG evaluation")
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=Path("eval/autorag/data"),
        help="Directory containing prepared parquet files",
    )
    parser.add_argument(
        "--chunk-config",
        type=Path,
        default=Path("eval/autorag/chunk_config.yaml"),
        help="YAML config for chunking sweep",
    )
    parser.add_argument(
        "--eval-config",
        type=Path,
        default=Path("eval/autorag/eval_config.yaml"),
        help="YAML config for retrieval evaluation",
    )
    parser.add_argument(
        "--project-dir",
        type=Path,
        default=Path("eval/autorag/results"),
        help="Directory for evaluation results",
    )
    args = parser.parse_args()

    args.project_dir.mkdir(parents=True, exist_ok=True)

    # Phase 1: Chunking sweep
    run_chunking(args.data_dir, args.chunk_config, args.project_dir)

    print(f"\nResults saved to: {args.project_dir}")
    print("Next step: review chunk/summary.csv and run retrieval evaluation")


if __name__ == "__main__":
    main()
