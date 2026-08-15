#!/usr/bin/env python
"""Prepare VA CPG corpus and QA data for AutoRAG evaluation.

Reads the extracted VA CPG markdown files and the QA dataset, then produces
three parquet files in the AutoRAG-expected format:

  - parsed.parquet  — full documents for the Chunker
  - corpus.parquet  — full documents for direct Evaluator use (optional)
  - qa.parquet      — questions with retrieval/generation ground truth

Usage:
    python eval/autorag/prepare_data.py
    python eval/autorag/prepare_data.py --corpus-dir /path/to/extracted --output-dir eval/autorag/data
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

DEFAULT_CORPUS_DIR = Path.home() / "Developer/retrieval-hub-data-sources/va-cpg/extracted"
DEFAULT_QA_JSON = Path(__file__).resolve().parent / "qa_dataset_draft.json"
DEFAULT_OUTPUT_DIR = Path(__file__).resolve().parent / "data"


def doc_id_from_path(rel_path: str) -> str:
    """Convert a relative path to a doc_id by stripping the .md extension.

    Example: 'chronic-disease/hypertension/clinician-summary.md'
           -> 'chronic-disease/hypertension/clinician-summary'
    """
    return rel_path.removesuffix(".md")


def load_corpus(corpus_dir: Path) -> pd.DataFrame:
    """Read all markdown files under corpus_dir and return a DataFrame.

    Each row represents one document with columns needed for AutoRAG's
    parsed data format (texts, doc_id, metadata).
    """
    records: list[dict] = []
    md_files = sorted(corpus_dir.rglob("*.md"))

    if not md_files:
        print(f"ERROR: No .md files found under {corpus_dir}", file=sys.stderr)
        sys.exit(1)

    for md_path in md_files:
        rel = md_path.relative_to(corpus_dir)
        parts = rel.parts  # e.g. ('chronic-disease', 'hypertension', 'clinician-summary.md')

        if len(parts) != 3:
            print(f"  SKIP (unexpected depth): {rel}")
            continue

        category, slug, filename = parts
        doc_type = filename.removesuffix(".md")
        rel_str = str(rel)
        did = doc_id_from_path(rel_str)

        text = md_path.read_text(encoding="utf-8")
        if not text.strip():
            print(f"  WARN: empty file {rel}")

        records.append(
            {
                "doc_id": did,
                "texts": text,
                "path": rel_str,
                "metadata": {
                    "last_modified_datetime": datetime.now(timezone.utc).isoformat(),
                    "prev_id": None,
                    "next_id": None,
                    "category": category,
                    "slug": slug,
                    "document_type": doc_type,
                },
            }
        )

    return pd.DataFrame(records)


def build_parsed(df: pd.DataFrame, output_dir: Path) -> Path:
    """Write parsed.parquet for the AutoRAG Chunker."""
    out = output_dir / "parsed.parquet"
    df.to_parquet(out, index=False)
    return out


def build_corpus(df: pd.DataFrame, output_dir: Path) -> Path:
    """Write corpus.parquet for the AutoRAG Evaluator.

    The Evaluator expects 'contents' instead of 'texts'.
    """
    corpus_df = df.rename(columns={"texts": "contents"})
    out = output_dir / "corpus.parquet"
    corpus_df.to_parquet(out, index=False)
    return out


def build_qa(qa_json_path: Path, valid_doc_ids: set[str], output_dir: Path) -> Path:
    """Read the QA JSON and write qa.parquet for the AutoRAG Evaluator."""
    with open(qa_json_path, encoding="utf-8") as f:
        data = json.load(f)

    questions = data["questions"]
    records: list[dict] = []
    missing_docs: list[str] = []

    for q in questions:
        qid = q["id"]
        query = q["question"]
        answer = q["answer"]

        # Convert source_doc path to doc_id format (strip .md)
        source_doc = q["source_doc"]
        did = doc_id_from_path(source_doc)

        if did not in valid_doc_ids:
            missing_docs.append(f"  {qid}: {did}")

        # AutoRAG expects retrieval_gt as list[list[str]]
        retrieval_gt = [[did]]

        # Include cross-CPG references if present
        for ref in q.get("cross_cpg_refs", []):
            ref_did = doc_id_from_path(ref)
            if ref_did in valid_doc_ids:
                retrieval_gt[0].append(ref_did)

        # AutoRAG expects generation_gt as list[str]
        generation_gt = [answer]

        records.append(
            {
                "qid": qid,
                "query": query,
                "retrieval_gt": retrieval_gt,
                "generation_gt": generation_gt,
            }
        )

    if missing_docs:
        print(f"\nWARN: {len(missing_docs)} question(s) reference doc_ids not in corpus:")
        for line in missing_docs:
            print(line)
        print("These questions will fail AutoRAG's validation.\n")

    qa_df = pd.DataFrame(records)
    out = output_dir / "qa.parquet"
    qa_df.to_parquet(out, index=False)
    return out


def validate(parsed_path: Path, qa_path: Path) -> bool:
    """Cross-validate that QA retrieval_gt doc_ids exist in the parsed corpus."""
    parsed_df = pd.read_parquet(parsed_path)
    qa_df = pd.read_parquet(qa_path)

    corpus_ids = set(parsed_df["doc_id"])
    all_ok = True

    for _, row in qa_df.iterrows():
        for gt_list in row["retrieval_gt"]:
            for did in gt_list:
                if did not in corpus_ids:
                    print(f"  FAIL: {row['qid']} references missing doc_id '{did}'")
                    all_ok = False

    return all_ok


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Prepare VA CPG data for AutoRAG evaluation"
    )
    parser.add_argument(
        "--corpus-dir",
        type=Path,
        default=DEFAULT_CORPUS_DIR,
        help="Root directory of extracted VA CPG markdown files",
    )
    parser.add_argument(
        "--qa-json",
        type=Path,
        default=DEFAULT_QA_JSON,
        help="Path to the QA dataset JSON file",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help="Directory for output parquet files",
    )
    args = parser.parse_args()

    if not args.corpus_dir.is_dir():
        print(f"ERROR: corpus directory not found: {args.corpus_dir}", file=sys.stderr)
        sys.exit(1)

    if not args.qa_json.is_file():
        print(f"ERROR: QA JSON not found: {args.qa_json}", file=sys.stderr)
        sys.exit(1)

    args.output_dir.mkdir(parents=True, exist_ok=True)

    # Step 1: Load and build parsed data
    print(f"Loading corpus from {args.corpus_dir} ...")
    df = load_corpus(args.corpus_dir)
    print(f"  Found {len(df)} documents")

    parsed_path = build_parsed(df, args.output_dir)
    print(f"  Wrote {parsed_path}")

    # Step 2: Build corpus data (for direct evaluator use)
    corpus_path = build_corpus(df, args.output_dir)
    print(f"  Wrote {corpus_path}")

    # Step 3: Build QA data
    print(f"\nLoading QA dataset from {args.qa_json} ...")
    valid_ids = set(df["doc_id"])
    qa_path = build_qa(args.qa_json, valid_ids, args.output_dir)

    qa_df = pd.read_parquet(qa_path)
    print(f"  Wrote {qa_path} ({len(qa_df)} questions)")

    # Step 4: Cross-validate
    print("\nValidating doc_id consistency ...")
    if validate(parsed_path, qa_path):
        print("  All retrieval_gt doc_ids found in corpus.")
    else:
        print("  Some doc_ids are missing. Fix the QA dataset or corpus before running AutoRAG.")

    # Summary
    categories = df["metadata"].apply(lambda m: m["category"]).value_counts()
    doc_types = df["metadata"].apply(lambda m: m["document_type"]).value_counts()

    print("\n--- Summary ---")
    print(f"Documents:  {len(df)}")
    print(f"Questions:  {len(qa_df)}")
    print(f"Categories: {dict(categories)}")
    print(f"Doc types:  {dict(doc_types)}")
    print(f"Output dir: {args.output_dir}")


if __name__ == "__main__":
    main()
