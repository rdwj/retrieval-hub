"""Ragas answer-quality comparison: TF-512-0 (sweep winner) vs TF-512-64 (baseline).

Three-stage pipeline:
  1. Retrieve top-5 from both chunking configurations
  2. Generate answers using a local LLM (Ollama) from retrieved context
  3. Score with Ragas (ContextPrecision + AnswerRelevancy) and compare

The production table has TF-512-64 data; the sweep table gets TF-512-0
data re-ingested (unless --skip-reingest is passed).

Usage:
    python scripts/eval_aircraft_answer_quality.py --embedding-endpoint URL
    python scripts/eval_aircraft_answer_quality.py --embedding-endpoint URL --skip-reingest
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import sys
import time
import types
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import psycopg
from openai import OpenAI
from pgvector.psycopg import register_vector

from retrieval_hub.ingestion.chunking.token_fixed import Chunk, chunk_document
from retrieval_hub.ingestion.embed import ChunkEmbedder, QueryEmbedder
from retrieval_hub.ingestion.normalize import NormalizedDocument, normalize_document
from retrieval_hub.ingestion.parse import ParsedDocument, ParsedSection
from retrieval_hub.ingestion.write import ensure_pgvector_schema, write_chunks

logger = logging.getLogger("eval_aircraft_answer_quality")

PRODUCTION_TABLE = "idx_aircraft_maintenance_v1"
SWEEP_TABLE = "idx_aircraft_maintenance_sweep"
EMBEDDING_MODEL = "Snowflake/snowflake-arctic-embed-m-v1.5"
EMBEDDING_DIMENSION = 768
DOCUMENT_PREFIX = ""
QUERY_PREFIX = "Represent this sentence for searching relevant passages: "

QA_DATASET_PATH = (
    Path(__file__).resolve().parent.parent / "eval" / "aircraft_maintenance" / "qa_dataset.json"
)
OUTPUT_PATH = (
    Path(__file__).resolve().parent.parent
    / "eval"
    / "aircraft_maintenance"
    / "ragas_chunking_comparison.json"
)
OUTPUT_DIR = Path(__file__).resolve().parent.parent / "eval" / "aircraft_maintenance"

DEFAULT_DATA_DIR = (
    Path(__file__).resolve().parent.parent.parent
    / "retrieval-hub-data-sources"
    / "aircraft-maintenance"
)
DEFAULT_VECTORS_DB_URL = (
    "postgresql+psycopg://retrievalhub:retrievalhub@127.0.0.1:5433/retrievalhub_vectors"
)
DEFAULT_ANSWER_LLM_URL = "http://localhost:11434/v1"
DEFAULT_ANSWER_LLM_MODEL = "gpt-oss:20b"
DEFAULT_SCORING_LLM_URL = (
    "https://gpt-oss-120b-direct-gpt-oss-120b-model"
    ".apps.cluster-z9hbt.z9hbt.sandbox1495.opentlc.com/v1"
)
DEFAULT_SCORING_LLM_MODEL = "/mnt/models"

TOP_K = 5

CONDITIONS = {
    "TF-512-0": {"table": SWEEP_TABLE, "chunk_tokens": 512, "overlap_tokens": 0},
    "TF-512-64": {"table": PRODUCTION_TABLE, "chunk_tokens": 512, "overlap_tokens": 64},
}

ANSWER_SYSTEM_PROMPT = (
    "You are an aircraft maintenance technical assistant with access to Piper "
    "Aircraft service bulletins for Cherokee (PA-28) and Saratoga (PA-32) "
    "families. Answer the user's question using ONLY the provided context. "
    "Cite the specific bulletin number and aircraft family for every claim. "
    "Be concise."
)

# Aircraft families to ingest, keyed by subdirectory name.
AIRCRAFT_FAMILIES: dict[str, str] = {
    "piper-cherokee": "Cherokee",
    "piper-saratoga": "Saratoga",
}

# Files to skip -- reference/index documents, not individual bulletins.
SKIP_STEMS: set[str] = {
    "Customer-Service-Info",
    "Service-Bulletin-Letter-Index",
    "Owner-Publications-Catalog",
    "urls",
}

_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$", re.MULTILINE)


# ---------------------------------------------------------------------------
# Document loading (adapted from sweep_aircraft_chunking.py)
# ---------------------------------------------------------------------------


def _make_doc_url(family_key: str, stem: str) -> str:
    aircraft = family_key.split("-", 1)[1] if "-" in family_key else family_key
    return f"piper://{aircraft}/{stem}"


def _make_doc_title(stem: str, family_label: str) -> str:
    return f"{stem} ({family_label})"


def _extract_sections_from_markdown(text: str) -> list[ParsedSection]:
    sections: list[ParsedSection] = []
    for match in _HEADING_RE.finditer(text):
        sections.append(
            ParsedSection(
                heading=match.group(2).strip(),
                level=len(match.group(1)),
                char_offset=match.start(),
            )
        )
    return sections


def _load_documents(data_dir: Path) -> list[NormalizedDocument]:
    """Load and normalize all aircraft maintenance documents."""
    documents: list[NormalizedDocument] = []
    skipped_short = 0

    for family_key, family_label in AIRCRAFT_FAMILIES.items():
        extracted_dir = data_dir / family_key / "extracted"
        manifest_path = extracted_dir / "manifest.json"

        if not manifest_path.exists():
            raise FileNotFoundError(f"manifest not found at {manifest_path}")

        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        logger.info(
            "loaded manifest for %s with %d entries from %s",
            family_label,
            len(manifest),
            manifest_path,
        )

        for entry in manifest:
            stem = Path(entry["source_path"]).stem
            if stem in SKIP_STEMS:
                continue

            md_path = extracted_dir / f"{stem}.md"
            if not md_path.exists():
                logger.warning("markdown not found for %s at %s; skipping", stem, md_path)
                continue

            raw_text = md_path.read_text(encoding="utf-8")
            doc_title = _make_doc_title(stem, family_label)
            doc_url = _make_doc_url(family_key, stem)

            sections = _extract_sections_from_markdown(raw_text)
            parsed = ParsedDocument(
                url=doc_url,
                title=doc_title,
                text=raw_text,
                content_type="text/markdown",
                sections=sections,
                metadata={"parser": "docling", "family": family_label},
            )

            normalized = normalize_document(parsed)
            if normalized is None:
                logger.debug("skipping short document: %s (%d chars)", doc_title, len(raw_text))
                skipped_short += 1
                continue

            documents.append(normalized)

    logger.info(
        "loaded %d documents (%d skipped as too short) across all families",
        len(documents),
        skipped_short,
    )
    if not documents:
        raise ValueError("no documents found in data directory")

    return documents


def _psycopg_dsn(vectors_db_url: str) -> str:
    return vectors_db_url.replace("postgresql+psycopg://", "postgresql://")


def _load_eval_questions() -> list[dict]:
    data = json.loads(QA_DATASET_PATH.read_text(encoding="utf-8"))
    return [q for q in data["questions"] if q.get("query_type") != "cross_dataset"]


# ---------------------------------------------------------------------------
# Re-ingestion: TF-512-0 into the sweep table
# ---------------------------------------------------------------------------


def _reingest_tf512_0(
    data_dir: Path,
    vectors_db_url: str,
    embedding_endpoint: str,
) -> None:
    logger.info("re-ingesting TF-512-0 into %s", SWEEP_TABLE)

    documents = _load_documents(data_dir)
    logger.info("loaded %d documents for re-ingestion", len(documents))

    all_chunks: list[Chunk] = []
    for doc in documents:
        chunks = chunk_document(doc, chunk_tokens=512, overlap_tokens=0)
        all_chunks.extend(chunks)

    logger.info("TF-512-0: %d chunks from %d documents", len(all_chunks), len(documents))

    embedder = ChunkEmbedder(
        model_name=EMBEDDING_MODEL,
        endpoint=embedding_endpoint,
        document_prefix=DOCUMENT_PREFIX,
    )
    ensure_pgvector_schema(vectors_db_url, SWEEP_TABLE, embedder.dimension)
    embeddings = embedder.embed_chunks(all_chunks)
    write_chunks(vectors_db_url, SWEEP_TABLE, all_chunks, embeddings, replace=True)
    logger.info("wrote %d rows to %s", len(all_chunks), SWEEP_TABLE)


# -- Stage 1: Retrieve -------------------------------------------------------


def _retrieve_from_table(
    table: str,
    query_vec,
    vectors_db_url: str,
    top_k: int = 5,
) -> list[dict]:
    dsn = _psycopg_dsn(vectors_db_url)
    with psycopg.connect(dsn) as conn:
        register_vector(conn)
        with conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT chunk_text, doc_title, doc_section,
                       1 - (embedding <=> %s::vector) AS score
                FROM {table}
                ORDER BY embedding <=> %s::vector
                LIMIT %s
                """,
                (query_vec, query_vec, top_k),
            )
            return [
                {"text": row[0], "doc_title": row[1], "doc_section": row[2], "score": float(row[3])}
                for row in cur.fetchall()
            ]


def _stage_retrieve(
    questions: list[dict],
    query_embedder: QueryEmbedder,
    vectors_db_url: str,
) -> dict[str, list[dict]]:
    results: dict[str, list[dict]] = {}
    for cond_id, cond in CONDITIONS.items():
        logger.info("retrieving for condition %s (table=%s)", cond_id, cond["table"])
        cond_results = []
        for i, q in enumerate(questions):
            query_vec = np.array(query_embedder.embed(q["question"]), dtype=np.float32)
            hits = _retrieve_from_table(cond["table"], query_vec, vectors_db_url, TOP_K)
            cond_results.append(
                {
                    "query_id": q["id"],
                    "question": q["question"],
                    "reference_answer": q["notes"],
                    "hits": hits,
                }
            )
            if (i + 1) % 5 == 0:
                logger.info("  [%d/%d] retrieved", i + 1, len(questions))
        results[cond_id] = cond_results
    return results


# -- Stage 2: Generate answers -----------------------------------------------


def _generate_answer(
    question: str,
    contexts: list[str],
    client: OpenAI,
    model: str,
) -> str:
    context_text = "\n\n".join(contexts)
    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": ANSWER_SYSTEM_PROMPT},
            {"role": "user", "content": f"Context:\n{context_text}\n\nQuestion: {question}"},
        ],
        temperature=0.0,
        max_tokens=1024,
    )
    return response.choices[0].message.content


def _stage_generate(
    retrieval: dict[str, list[dict]],
    answer_client: OpenAI,
    answer_model: str,
) -> dict[str, list[dict]]:
    results: dict[str, list[dict]] = {}
    for cond_id, items in retrieval.items():
        logger.info("generating answers for condition %s", cond_id)
        cond_results = []
        for i, item in enumerate(items):
            contexts = [h["text"] for h in item["hits"]]
            answer = _generate_answer(item["question"], contexts, answer_client, answer_model)
            cond_results.append({**item, "answer": answer})
            if (i + 1) % 5 == 0:
                logger.info("  [%d/%d] generated", i + 1, len(items))
        results[cond_id] = cond_results
    return results


# -- Stage 3: Score with Ragas ------------------------------------------------


def _stub_vertexai():
    try:
        import langchain_community.chat_models as cm  # noqa: F401
    except ImportError:
        return
    mod = types.ModuleType("langchain_community.chat_models.vertexai")
    mod.ChatVertexAI = type("ChatVertexAI", (), {})
    sys.modules["langchain_community.chat_models.vertexai"] = mod


def _stage_score(
    generated: dict[str, list[dict]],
    scoring_llm_url: str,
    scoring_llm_model: str,
    max_workers: int = 2,
) -> dict[str, dict]:
    _stub_vertexai()

    import warnings

    warnings.filterwarnings("ignore", category=DeprecationWarning)

    from langchain_community.embeddings import HuggingFaceEmbeddings
    from ragas import EvaluationDataset, SingleTurnSample, evaluate
    from ragas.llms import llm_factory
    from ragas.metrics._answer_relevance import AnswerRelevancy
    from ragas.metrics._context_precision import ContextPrecision
    from ragas.run_config import RunConfig

    client = OpenAI(api_key="local", base_url=scoring_llm_url)
    if "gpt-oss-120b" in scoring_llm_url or scoring_llm_model == "/mnt/models":
        original_create = client.chat.completions.create

        def _patched_create(*args, **kwargs):
            extra_body = kwargs.get("extra_body", {}) or {}
            extra_body["chat_template_kwargs"] = {"enable_thinking": False}
            kwargs["extra_body"] = extra_body
            return original_create(*args, **kwargs)

        client.chat.completions.create = _patched_create

    llm = llm_factory(scoring_llm_model, client=client, max_tokens=8192)
    embeddings = HuggingFaceEmbeddings(
        model_name=EMBEDDING_MODEL,
        cache_folder=".model_cache",
    )
    ragas_run_config = RunConfig(max_workers=max_workers, timeout=600)
    metrics = [ContextPrecision(), AnswerRelevancy()]

    scores: dict[str, dict] = {}
    for cond_id, items in generated.items():
        checkpoint_path = OUTPUT_DIR / f"scores_{cond_id}.json"
        if checkpoint_path.exists():
            logger.info("scoring %s: using checkpoint %s", cond_id, checkpoint_path)
            scores[cond_id] = json.loads(checkpoint_path.read_text())
            continue

        logger.info("scoring %s (%d workers)...", cond_id, max_workers)
        samples = [
            SingleTurnSample(
                user_input=item["question"],
                retrieved_contexts=[h["text"] for h in item["hits"]],
                response=item["answer"],
                reference=item["reference_answer"],
            )
            for item in items
        ]
        dataset = EvaluationDataset(samples=samples)
        ragas_result = evaluate(
            dataset=dataset,
            metrics=metrics,
            llm=llm,
            embeddings=embeddings,
            run_config=ragas_run_config,
        )
        df = ragas_result.to_pandas()
        metric_names = [m.name for m in metrics]

        per_question = []
        for idx, item in enumerate(items):
            row = {"query_id": item["query_id"]}
            for mn in metric_names:
                row[mn] = float(df.iloc[idx][mn])
            per_question.append(row)

        agg = {mn: float(df[mn].mean()) for mn in metric_names}
        condition_result = {"aggregate": agg, "per_query": per_question}

        checkpoint_path.write_text(json.dumps(condition_result, indent=2) + "\n")
        logger.info("scoring %s complete, checkpoint saved", cond_id)
        scores[cond_id] = condition_result

    return scores


# -- Orchestrator -------------------------------------------------------------


def _print_comparison(scores: dict[str, dict]) -> None:
    cond_ids = list(CONDITIONS.keys())
    a, b = cond_ids[0], cond_ids[1]
    agg_a = scores[a]["aggregate"]
    agg_b = scores[b]["aggregate"]
    metric_names = list(agg_a.keys())

    print()
    print("=" * 60)
    header = f"{'Metric':<22} {a:>10} {b:>10} {'Delta':>10}"
    print(header)
    print("-" * 60)
    for mn in metric_names:
        delta = agg_a[mn] - agg_b[mn]
        print(f"{mn:<22} {agg_a[mn]:>10.3f} {agg_b[mn]:>10.3f} {delta:>+10.3f}")
    print("=" * 60)


def _run(args: argparse.Namespace) -> int:
    wall_start = time.monotonic()

    questions = _load_eval_questions()
    logger.info("loaded %d eval questions", len(questions))

    if not args.skip_reingest:
        _reingest_tf512_0(args.data_dir, args.vectors_db_url, args.embedding_endpoint)

    logger.info("initializing query embedder: model=%s endpoint=%s", EMBEDDING_MODEL, args.embedding_endpoint)
    query_embedder = QueryEmbedder(
        model_name=EMBEDDING_MODEL,
        endpoint=args.embedding_endpoint,
        query_prefix=QUERY_PREFIX,
    )

    logger.info("stage 1: retrieve")
    retrieval = _stage_retrieve(questions, query_embedder, args.vectors_db_url)

    logger.info("stage 2: generate answers")
    answer_client = OpenAI(api_key="local", base_url=args.answer_llm_url)
    generated = _stage_generate(retrieval, answer_client, args.answer_llm_model)

    logger.info("stage 3: score with Ragas")
    scores = _stage_score(
        generated,
        scoring_llm_url=args.scoring_llm_url,
        scoring_llm_model=args.scoring_llm_model,
    )

    output = {
        "date": datetime.now(UTC).strftime("%Y-%m-%d"),
        "conditions": {
            cond_id: {
                "table": CONDITIONS[cond_id]["table"],
                **scores[cond_id],
            }
            for cond_id in CONDITIONS
        },
    }
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps(output, indent=2) + "\n")
    logger.info("wrote results to %s", OUTPUT_PATH)

    wall_time = time.monotonic() - wall_start
    _print_comparison(scores)
    print(f"\n  Wall time: {wall_time:.1f}s")
    print(f"  Output:    {OUTPUT_PATH}")

    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=DEFAULT_DATA_DIR,
        help=f"Path to aircraft-maintenance data directory. Default: {DEFAULT_DATA_DIR}",
    )
    parser.add_argument(
        "--embedding-endpoint",
        required=True,
        help="Base URL of an OpenAI-compatible embedding endpoint (e.g. https://vllm-host:8000).",
    )
    parser.add_argument(
        "--vectors-db-url",
        default=DEFAULT_VECTORS_DB_URL,
        help=f"SQLAlchemy URL for vectors DB. Default: {DEFAULT_VECTORS_DB_URL}",
    )
    parser.add_argument(
        "--answer-llm-url",
        default=DEFAULT_ANSWER_LLM_URL,
        help=f"Answer LLM URL. Default: {DEFAULT_ANSWER_LLM_URL}",
    )
    parser.add_argument(
        "--answer-llm-model",
        default=DEFAULT_ANSWER_LLM_MODEL,
        help=f"Answer LLM model. Default: {DEFAULT_ANSWER_LLM_MODEL}",
    )
    parser.add_argument(
        "--scoring-llm-url",
        default=DEFAULT_SCORING_LLM_URL,
        help="Ragas scoring LLM URL.",
    )
    parser.add_argument(
        "--scoring-llm-model",
        default=DEFAULT_SCORING_LLM_MODEL,
        help=f"Ragas scoring model. Default: {DEFAULT_SCORING_LLM_MODEL}",
    )
    parser.add_argument(
        "--skip-reingest",
        action="store_true",
        help="Skip re-ingestion of TF-512-0 into sweep table.",
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

    return _run(args)


if __name__ == "__main__":
    sys.exit(main())
