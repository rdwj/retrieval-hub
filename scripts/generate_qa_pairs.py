#!/usr/bin/env python
"""Generate Q/A pairs from source documents using an OpenAI-compatible LLM.

Discovers .md, .txt, and .html files in a corpus directory and generates
evaluation questions with ground-truth answers. Supports any retrieval-hub
source via --source-slug and --family flags.

Usage:
    python scripts/generate_qa_pairs.py --source-slug va-cpg --data-dir ~/corpus/va-cpg
    python scripts/generate_qa_pairs.py --source-slug my-source --family document --num-pairs 30
    python scripts/generate_qa_pairs.py --source-slug va-cpg --dry-run
"""

from __future__ import annotations

import argparse
import json
import logging
import math
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
DEFAULT_OUTPUT_TEMPLATE = "eval/{source_slug}/qa_generated.json"
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

_JSON_FORMAT_INSTRUCTIONS = """
Return a JSON object with a single key "questions" containing an array of objects. \
Each object must have exactly these fields:
- "question": the question text (string)
- "answer": ground-truth answer directly supported by the source text (string)
- "source_section": section heading where the answer is found (string)
- "query_type": one of "factoid", "treatment", "procedure", "differential", "eligibility" (string)
- "language_register": "clinical" or "lay" (string)

Return ONLY the JSON object, no other text."""

_REGISTER_INSTRUCTIONS = """\
- For "lay" register: use plain language, avoid jargon, phrase as a non-expert \
might ask
- For "clinical" register: use domain terminology as a practitioner would"""

SYSTEM_PROMPTS: dict[str, str] = {
    "clinical_document": (
        "You are a clinical domain expert. Generate question/answer pairs from "
        "the following clinical documentation for {source_name}.\n\n"
        "Requirements:\n"
        "- Each question must be answerable from the provided text\n"
        "- Answers must quote or closely paraphrase specific text from the source\n"
        "- Include the source section name (heading) where the answer is found\n"
        "- Generate a mix of query types: factoid, treatment, procedure, "
        "differential, eligibility\n"
        f"{_REGISTER_INSTRUCTIONS}\n"
        f"{_JSON_FORMAT_INSTRUCTIONS}"
    ),
    "document": (
        "You are a knowledge base expert. Generate question/answer pairs from "
        "the following documentation for {source_name}.\n\n"
        "Requirements:\n"
        "- Each question must be answerable from the provided text\n"
        "- Answers must quote or closely paraphrase specific text from the source\n"
        "- Include the source section name (heading) where the answer is found\n"
        "- Generate a mix of query types: factoid, treatment, procedure, "
        "differential, eligibility\n"
        f"{_REGISTER_INSTRUCTIONS}\n"
        f"{_JSON_FORMAT_INSTRUCTIONS}"
    ),
    "technical_document": (
        "You are a technical documentation expert. Generate question/answer "
        "pairs from the following technical documentation for {source_name}.\n\n"
        "Requirements:\n"
        "- Each question must be answerable from the provided text\n"
        "- Answers must quote or closely paraphrase specific text from the source\n"
        "- Include the source section name (heading) where the answer is found\n"
        "- Generate a mix of query types: factoid, treatment, procedure, "
        "differential, eligibility\n"
        f"{_REGISTER_INSTRUCTIONS}\n"
        f"{_JSON_FORMAT_INSTRUCTIONS}"
    ),
    "code": (
        "You are a software engineering expert. Generate question/answer pairs "
        "about the following code from {source_name}.\n\n"
        "Requirements:\n"
        "- Each question must be answerable from the provided text\n"
        "- Answers must quote or closely paraphrase specific text from the source\n"
        "- Include the source section name (heading or file section) where the "
        "answer is found\n"
        "- Generate a mix of query types: factoid, treatment, procedure, "
        "differential, eligibility\n"
        f"{_REGISTER_INSTRUCTIONS}\n"
        f"{_JSON_FORMAT_INSTRUCTIONS}"
    ),
}

VALID_FAMILIES = tuple(SYSTEM_PROMPTS.keys())


def _make_user_prompt(
    source_text: str,
    num_questions: int,
    slug: str,
    source_name: str,
    category: str,
) -> str:
    n_clinical = num_questions // 2
    n_lay = num_questions - n_clinical
    return (
        f"Below is documentation from {source_name} on {category}/{slug}.\n\n"
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
    *,
    system_prompt: str,
    source_name: str,
    category: str,
    max_retries: int = 3,
) -> list[dict]:
    """Generate Q/A pairs for a single document. Returns parsed question dicts."""
    user_prompt = _make_user_prompt(
        source_text, num_questions, slug, source_name, category,
    )

    for attempt in range(max_retries):
        try:
            stream = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": system_prompt},
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


def _discover_documents(data_dir: Path) -> list[tuple[str, str, str]]:
    """Walk *data_dir* for .md, .txt, .html files.

    Returns a sorted list of ``(slug, category, relative_path)`` tuples.
    *slug* is the file stem; *category* is the first path component (or
    ``"general"`` for files directly in *data_dir*).
    """
    extensions = {".md", ".txt", ".html"}
    targets: list[tuple[str, str, str]] = []
    for path in sorted(data_dir.rglob("*")):
        if path.is_file() and path.suffix in extensions:
            rel = path.relative_to(data_dir)
            parts = rel.parts
            slug = path.stem
            category = parts[0] if len(parts) > 1 else "general"
            targets.append((slug, category, str(rel)))
    return targets


def _build_generation_targets(
    data_dir: Path,
    source_slug: str,
    num_pairs: int,
) -> list[tuple[str, str, str, int]]:
    """Build generation targets from directory discovery or backward-compat fallback.

    For the original VA CPG source with its default corpus directory, the
    hardcoded ``GENERATION_TARGETS`` list is returned so that existing
    workflows produce identical output.
    """
    va_slugs = {"va-cpg", "va-cpg-clinical-guidelines"}
    if source_slug in va_slugs and data_dir == DEFAULT_CORPUS_DIR:
        return list(GENERATION_TARGETS)

    docs = _discover_documents(data_dir)
    if not docs:
        logger.warning("no documents found in %s", data_dir)
        return []

    if len(docs) <= num_pairs:
        per_doc = max(1, math.ceil(num_pairs / len(docs)))
        return [(slug, cat, rel, per_doc) for slug, cat, rel in docs]

    import random
    sampled = random.sample(docs, num_pairs)
    return [(slug, cat, rel, 1) for slug, cat, rel in sampled]


def generate_pairs(
    data_dir: Path,
    source_slug: str,
    source_name: str,
    family: str,
    num_pairs: int,
    llm_url: str,
    llm_model: str,
    output_path: Path,
    existing_dataset_path: Path | None = None,
    dry_run: bool = False,
) -> dict:
    """Generate QA pairs from documents in *data_dir*.

    Returns the output dataset dict (also written to *output_path*).
    """
    targets = _build_generation_targets(data_dir, source_slug, num_pairs)
    if not targets:
        logger.error("no generation targets for source %s", source_slug)
        return {"metadata": {}, "questions": []}

    # Determine starting ID from existing dataset
    start_id = 1
    if existing_dataset_path and existing_dataset_path.exists():
        existing = json.loads(
            existing_dataset_path.read_text(encoding="utf-8"),
        )
        max_id = max(
            int(q["id"].lstrip("q")) for q in existing["questions"]
        )
        start_id = max_id + 1
        logger.info(
            "existing dataset has %d questions (max id q%03d), starting at q%03d",
            len(existing["questions"]), max_id, start_id,
        )

    total_planned = sum(t[3] for t in targets)
    logger.info(
        "generation plan: %d documents, %d total questions",
        len(targets), total_planned,
    )

    if dry_run:
        print(f"\nDry run — would generate {total_planned} questions:\n")
        for slug, category, path, n in targets:
            src = data_dir / path
            exists = src.exists()
            print(
                f"  {slug:<25} {category:<18} n={n}  "
                f"source={'OK' if exists else 'MISSING'}"
            )
        print()
        return {"metadata": {}, "questions": []}

    system_prompt = SYSTEM_PROMPTS[family].format(source_name=source_name)

    client = OpenAI(
        api_key="local",
        base_url=llm_url,
        http_client=httpx.Client(timeout=httpx.Timeout(300.0, connect=30.0)),
    )
    all_questions: list[dict] = []
    current_id = start_id
    stats = {"generated": 0, "validated": 0, "skipped": 0, "failed_docs": 0}

    for slug, category, rel_path, num in targets:
        src_path = data_dir / rel_path
        if not src_path.exists():
            logger.error("source file missing: %s", src_path)
            stats["failed_docs"] += 1
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
            client, llm_model, source_text, slug, num,
            system_prompt=system_prompt,
            source_name=source_name,
            category=category,
        )

        if not raw_questions:
            stats["failed_docs"] += 1
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

    # Build output
    output_data = {
        "metadata": {
            "version": "generated-v1",
            "created": datetime.now(UTC).strftime("%Y-%m-%d"),
            "question_count": len(all_questions),
            "source_slug": source_slug,
            "family": family,
            "description": f"LLM-generated Q/A pairs for {source_name}",
            "categories_covered": sorted(
                set(q["category"] for q in all_questions),
            ),
            "docs_covered": len(set(q["cpg_slug"] for q in all_questions)),
        },
        "questions": all_questions,
    }

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(output_data, indent=2) + "\n", encoding="utf-8",
    )

    logger.info(
        "done: %d generated, %d validated, %d skipped, %d failed docs "
        "=> %d written to %s",
        stats["generated"], stats["validated"], stats["skipped"],
        stats["failed_docs"], len(all_questions), output_path,
    )

    # Print distribution summary
    from collections import Counter
    cats = Counter(q["category"] for q in all_questions)
    regs = Counter(q["language_register"] for q in all_questions)
    print(f"\nGenerated {len(all_questions)} questions:")
    print(f"  By category: {dict(sorted(cats.items()))}")
    print(f"  By register: {dict(sorted(regs.items()))}")

    return output_data


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source-slug", required=True,
        help="Source slug being onboarded (e.g. 'va-cpg', 'my-docs').",
    )
    parser.add_argument(
        "--source-name", default=None,
        help="Human-readable source name for prompts. "
        "Defaults to title-cased slug.",
    )
    parser.add_argument(
        "--family", default="document", choices=VALID_FAMILIES,
        help="Document family (controls system prompt). Default: document.",
    )
    parser.add_argument(
        "--num-pairs", type=int, default=20,
        help="Total number of QA pairs to generate. Default: 20.",
    )
    parser.add_argument(
        "--corpus-dir", "--data-dir", type=Path, default=DEFAULT_CORPUS_DIR,
        dest="data_dir",
        help=f"Source corpus directory. Default: {DEFAULT_CORPUS_DIR}",
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
        "--output", type=Path, default=None,
        help="Output JSON path. Default: eval/<source-slug>/qa_generated.json",
    )
    parser.add_argument(
        "--existing-dataset", type=Path, default=DEFAULT_EXISTING,
        help=f"Existing QA dataset for ID continuity. Default: {DEFAULT_EXISTING}",
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

    source_name = args.source_name or args.source_slug.replace("-", " ").title()

    output_path = args.output or Path(
        DEFAULT_OUTPUT_TEMPLATE.format(source_slug=args.source_slug),
    )

    generate_pairs(
        data_dir=args.data_dir,
        source_slug=args.source_slug,
        source_name=source_name,
        family=args.family,
        num_pairs=args.num_pairs,
        llm_url=args.llm_url,
        llm_model=args.llm_model,
        output_path=output_path,
        existing_dataset_path=args.existing_dataset,
        dry_run=args.dry_run,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
