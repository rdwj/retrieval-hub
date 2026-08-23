#!/usr/bin/env python
"""Generate Q/A pairs from VA CPG source documents using gpt-oss-120b.

Reads clinician-summary.md files from the VA CPG corpus and generates
evaluation questions with ground-truth answers, targeting under-represented
CPGs and categories.

Usage:
    python scripts/generate_qa_pairs.py
    python scripts/generate_qa_pairs.py --dry-run
    python scripts/generate_qa_pairs.py --output eval/autorag/qa_generated.json
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

import httpx
from openai import OpenAI

logger = logging.getLogger("generate_qa_pairs")

DEFAULT_CORPUS_DIR = Path.home() / "Developer/retrieval-hub-data-sources/va-cpg/extracted"
DEFAULT_LLM_URL = (
    "https://gpt-oss-120b-direct-gpt-oss-120b-model"
    ".apps.cluster-z9hbt.z9hbt.sandbox1495.opentlc.com/v1"
)
DEFAULT_LLM_MODEL = "/mnt/models"
DEFAULT_OUTPUT = Path("eval/autorag/qa_generated.json")
DEFAULT_EXISTING = Path("eval/autorag/qa_dataset_draft.json")

GENERATION_TARGETS = [
    # (slug, category, path_in_corpus, num_to_generate)
    # Zero-question CPGs
    ("asthma", "chronic-disease", "chronic-disease/asthma/clinician-summary.md", 4),
    ("ckd", "chronic-disease", "chronic-disease/ckd/clinician-summary.md", 4),
    ("cmi", "chronic-disease", "chronic-disease/cmi/clinician-summary.md", 4),
    ("lipids", "chronic-disease", "chronic-disease/lipids/clinician-summary.md", 4),
    ("bipolar", "mental-health", "mental-health/bipolar/clinician-summary.md", 4),
    ("schizophrenia", "mental-health", "mental-health/schizophrenia/clinician-summary.md", 4),
    ("lower-limb-amputation", "rehabilitation", "rehabilitation/lower-limb-amputation/clinician-summary.md", 4),
    ("upper-limb-amputation", "rehabilitation", "rehabilitation/upper-limb-amputation/clinician-summary.md", 4),
    ("tinnitus", "rehabilitation", "chronic-disease/tinnitus/clinician-summary.md", 4),
    # Under-represented CPGs (1 existing question each)
    ("headache", "pain", "pain/headache/clinician-summary.md", 3),
    ("insomnia-osa", "chronic-disease", "chronic-disease/insomnia-osa/clinician-summary.md", 3),
    ("obesity", "chronic-disease", "chronic-disease/obesity/clinician-summary.md", 3),
    ("osteoarthritis", "chronic-disease", "chronic-disease/osteoarthritis/clinician-summary.md", 3),
    ("tobacco", "chronic-disease", "chronic-disease/tobacco/clinician-summary.md", 3),
    # Boost under-represented categories
    ("stroke", "rehabilitation", "rehabilitation/stroke/clinician-summary.md", 3),
    ("mtbi", "rehabilitation", "rehabilitation/mtbi/clinician-summary.md", 3),
    ("pregnancy", "womens-health", "womens-health/pregnancy/clinician-summary.md", 6),
    ("lower-back-pain", "pain", "pain/lower-back-pain/clinician-summary.md", 3),
    ("opioids", "pain", "pain/opioids/clinician-summary.md", 3),
]

SYSTEM_PROMPT = """\
You are a clinical evaluation dataset creator. Given a VA/DoD Clinical Practice \
Guideline (CPG) summary, generate evaluation questions with ground-truth answers.

Requirements:
- Each question must be answerable from the provided text
- Answers must quote or closely paraphrase specific text from the source
- Include the source section name (heading) where the answer is found
- Generate a mix of query types: factoid, treatment, procedure, differential, eligibility
- For "lay" register: use patient-friendly language, avoid medical jargon, \
phrase as a patient might ask their doctor
- For "clinical" register: use clinical terminology as a provider would

Return a JSON object with a single key "questions" containing an array of objects. \
Each object must have exactly these fields:
- "question": the question text (string)
- "answer": ground-truth answer directly supported by the source text (string)
- "source_section": section heading where the answer is found (string)
- "query_type": one of "factoid", "treatment", "procedure", "differential", "eligibility" (string)
- "language_register": "clinical" or "lay" (string)

Return ONLY the JSON object, no other text."""


def _make_user_prompt(source_text: str, num_questions: int, slug: str) -> str:
    n_clinical = num_questions // 2
    n_lay = num_questions - n_clinical
    return (
        f"Below is the clinician summary for the VA/DoD CPG on {slug}.\n\n"
        f"Generate exactly {num_questions} evaluation questions: "
        f"{n_clinical} in clinical register and {n_lay} in lay register.\n\n"
        f"Distribute across query types (factoid, treatment, procedure, "
        f"differential, eligibility) — avoid putting all questions in one type.\n\n"
        f"Source document:\n\n{source_text}"
    )


def _validate_answer(answer: str, source_text: str) -> bool:
    """Check that key phrases from the answer appear in the source document."""
    answer_lower = answer.lower()
    source_lower = source_text.lower()
    words = re.findall(r'\b\w+\b', answer_lower)
    if len(words) < 5:
        return answer_lower in source_lower

    # Check for overlapping 5-grams between answer and source
    def ngrams(text: str, n: int) -> set[str]:
        tokens = re.findall(r'\b\w+\b', text)
        return {" ".join(tokens[i:i+n]) for i in range(len(tokens) - n + 1)}

    answer_5grams = ngrams(answer_lower, 5)
    source_5grams = ngrams(source_lower, 5)
    overlap = answer_5grams & source_5grams
    if not answer_5grams:
        return False
    return len(overlap) / len(answer_5grams) >= 0.15


def _generate_for_cpg(
    client: OpenAI,
    model: str,
    source_text: str,
    slug: str,
    num_questions: int,
    max_retries: int = 3,
) -> list[dict]:
    """Generate Q/A pairs for a single CPG. Returns parsed question dicts."""
    user_prompt = _make_user_prompt(source_text, num_questions, slug)

    for attempt in range(max_retries):
        try:
            stream = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=0.7,
                max_tokens=4096,
                extra_body={"chat_template_kwargs": {"enable_thinking": False}},
                response_format={"type": "json_object"},
                stream=True,
            )
            chunks = []
            for chunk in stream:
                if chunk.choices and chunk.choices[0].delta.content:
                    chunks.append(chunk.choices[0].delta.content)
            content = "".join(chunks)
            parsed = json.loads(content)

            questions = parsed.get("questions", [])
            if not questions:
                logger.warning(
                    "%s attempt %d: no questions in response", slug, attempt + 1
                )
                continue

            valid = []
            for q in questions:
                required = {"question", "answer", "source_section",
                            "query_type", "language_register"}
                if not required.issubset(q.keys()):
                    logger.warning(
                        "%s: skipping question with missing fields: %s",
                        slug, required - q.keys(),
                    )
                    continue
                if q["query_type"] not in (
                    "factoid", "treatment", "procedure", "differential", "eligibility"
                ):
                    q["query_type"] = "factoid"
                if q["language_register"] not in ("clinical", "lay"):
                    q["language_register"] = "clinical"
                valid.append(q)

            return valid

        except json.JSONDecodeError as e:
            logger.warning(
                "%s attempt %d: failed to parse JSON: %s", slug, attempt + 1, e
            )
        except Exception as e:
            logger.warning(
                "%s attempt %d: LLM call failed: %s", slug, attempt + 1, e
            )

        if attempt < max_retries - 1:
            time.sleep(2 ** attempt)

    logger.error("%s: all %d attempts failed", slug, max_retries)
    return []


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--corpus-dir", type=Path, default=DEFAULT_CORPUS_DIR,
        help=f"VA CPG extracted corpus directory. Default: {DEFAULT_CORPUS_DIR}",
    )
    parser.add_argument(
        "--llm-url", default=DEFAULT_LLM_URL,
        help="LLM endpoint base URL (OpenAI-compatible /v1).",
    )
    parser.add_argument(
        "--llm-model", default=DEFAULT_LLM_MODEL,
        help=f"LLM model name. Default: {DEFAULT_LLM_MODEL}",
    )
    parser.add_argument(
        "--output", type=Path, default=DEFAULT_OUTPUT,
        help=f"Output JSON path. Default: {DEFAULT_OUTPUT}",
    )
    parser.add_argument(
        "--existing-dataset", type=Path, default=DEFAULT_EXISTING,
        help=f"Existing QA dataset to check for ID continuity. Default: {DEFAULT_EXISTING}",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Show generation plan without making LLM calls.",
    )
    parser.add_argument(
        "--log-level", default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=args.log_level,
        format="%(asctime)s %(levelname)-5s %(name)s: %(message)s",
    )

    # Determine starting ID from existing dataset
    start_id = 51
    if args.existing_dataset.exists():
        existing = json.loads(args.existing_dataset.read_text(encoding="utf-8"))
        max_id = max(
            int(q["id"].lstrip("q")) for q in existing["questions"]
        )
        start_id = max_id + 1
        logger.info(
            "existing dataset has %d questions (max id q%03d), starting at q%03d",
            len(existing["questions"]), max_id, start_id,
        )

    # Compute plan
    total_planned = sum(t[3] for t in GENERATION_TARGETS)
    logger.info(
        "generation plan: %d CPGs, %d total questions",
        len(GENERATION_TARGETS), total_planned,
    )

    if args.dry_run:
        print(f"\nDry run — would generate {total_planned} questions:\n")
        for slug, category, path, n in GENERATION_TARGETS:
            src = args.corpus_dir / path
            exists = src.exists()
            print(f"  {slug:<25} {category:<18} n={n}  source={'OK' if exists else 'MISSING'}")
        print()
        return 0

    client = OpenAI(
        api_key="local",
        base_url=args.llm_url,
        http_client=httpx.Client(timeout=httpx.Timeout(300.0, connect=30.0)),
    )
    all_questions: list[dict] = []
    current_id = start_id
    stats = {"generated": 0, "validated": 0, "skipped": 0, "failed_cpgs": 0}

    for slug, category, rel_path, num in GENERATION_TARGETS:
        src_path = args.corpus_dir / rel_path
        if not src_path.exists():
            logger.error("source file missing: %s", src_path)
            stats["failed_cpgs"] += 1
            continue

        source_text = src_path.read_text(encoding="utf-8")
        max_chars = 40_000
        if len(source_text) > max_chars:
            logger.info(
                "[%s] truncating source from %d to %d chars",
                slug, len(source_text), max_chars,
            )
            source_text = source_text[:max_chars]
        logger.info(
            "[%s] generating %d questions from %s (%d chars)...",
            slug, num, rel_path, len(source_text),
        )

        raw_questions = _generate_for_cpg(
            client, args.llm_model, source_text, slug, num,
        )

        if not raw_questions:
            stats["failed_cpgs"] += 1
            continue

        stats["generated"] += len(raw_questions)

        for q in raw_questions:
            if _validate_answer(q["answer"], source_text):
                stats["validated"] += 1
                all_questions.append({
                    "id": f"q{current_id:03d}",
                    "question": q["question"],
                    "answer": q["answer"],
                    "source_doc": rel_path,
                    "source_section": q["source_section"],
                    "query_type": q["query_type"],
                    "language_register": q["language_register"],
                    "category": category,
                    "cpg_slug": slug,
                })
                current_id += 1
            else:
                stats["skipped"] += 1
                logger.warning(
                    "[%s] weak validation for question: %.80s...",
                    slug, q["question"],
                )

    # Write output
    output_data = {
        "metadata": {
            "version": "generated-v1",
            "created": datetime.now(UTC).strftime("%Y-%m-%d"),
            "question_count": len(all_questions),
            "description": "LLM-generated Q/A pairs for eval expansion",
            "generator": "gpt-oss-120b",
            "categories_covered": sorted(set(q["category"] for q in all_questions)),
            "cpgs_covered": len(set(q["cpg_slug"] for q in all_questions)),
        },
        "questions": all_questions,
    }

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(output_data, indent=2) + "\n", encoding="utf-8")

    logger.info(
        "done: %d generated, %d validated, %d skipped, %d failed CPGs => %d written to %s",
        stats["generated"], stats["validated"], stats["skipped"],
        stats["failed_cpgs"], len(all_questions), args.output,
    )

    # Print distribution summary
    from collections import Counter
    cats = Counter(q["category"] for q in all_questions)
    regs = Counter(q["language_register"] for q in all_questions)
    print(f"\nGenerated {len(all_questions)} questions:")
    print(f"  By category: {dict(sorted(cats.items()))}")
    print(f"  By register: {dict(sorted(regs.items()))}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
