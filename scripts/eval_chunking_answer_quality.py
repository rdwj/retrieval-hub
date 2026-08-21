"""Ragas answer-quality comparison: SA-256-0 (winner) vs SA-512-0 (baseline).

Three-stage pipeline:
  1. Retrieve top-5 from both chunking configurations
  2. Generate answers using a local LLM (Ollama) from retrieved context
  3. Score with Ragas (ContextPrecision + AnswerRelevancy) and compare

The production table has SA-256-0 data; the sweep table gets SA-512-0
data re-ingested (unless --skip-reingest is passed).

Usage:
    python scripts/eval_chunking_answer_quality.py
    python scripts/eval_chunking_answer_quality.py --skip-reingest
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
import types
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import psycopg
from openai import OpenAI
from pgvector.psycopg import register_vector

from retrieval_hub.ingestion.chunking.bioc_section import chunk_bioc_document
from retrieval_hub.ingestion.chunking.token_fixed import Chunk
from retrieval_hub.ingestion.embed import ChunkEmbedder
from retrieval_hub.ingestion.write import ensure_pgvector_schema, write_chunks

logger = logging.getLogger("eval_chunking_answer_quality")

PRODUCTION_TABLE = "idx_pubmed_hypertension_v1"
SWEEP_TABLE = "idx_pubmed_hypertension_sweep"
EMBEDDING_MODEL = "NeuML/pubmedbert-base-embeddings"
EMBEDDING_DIMENSION = 768
DOCUMENT_PREFIX = ""
SKIP_SECTIONS = frozenset({"AUTH_CONT", "SUPPL", "REF", "COMP_INT"})

QA_DATASET_PATH = Path("eval/pubmed_hypertension/qa_dataset.json")
OUTPUT_PATH = Path("eval/pubmed_hypertension/ragas_chunking_comparison.json")
OUTPUT_DIR = Path("eval/pubmed_hypertension")

DEFAULT_DATA_DIR = (
    Path(__file__).resolve().parent.parent.parent
    / "retrieval-hub-data-sources"
    / "pubmed-hypertension"
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
    "SA-256-0": {"table": PRODUCTION_TABLE, "chunk_tokens": 256, "overlap_tokens": 0},
    "SA-512-0": {"table": SWEEP_TABLE, "chunk_tokens": 512, "overlap_tokens": 0},
}

ANSWER_SYSTEM_PROMPT = (
    "You are a biomedical research assistant with access to PubMed review "
    "articles on hypertension. Answer the user's question using ONLY the "
    "provided context. If the context does not contain enough information "
    "to answer fully, say so. Cite the article when possible. Be concise."
)


def _psycopg_dsn(vectors_db_url: str) -> str:
    return vectors_db_url.replace("postgresql+psycopg://", "postgresql://")


def _load_eval_questions() -> list[dict]:
    data = json.loads(QA_DATASET_PATH.read_text(encoding="utf-8"))
    return [q for q in data["questions"] if q.get("source_doc") != "cross-dataset"]


def _reingest_sa512(data_dir: Path, vectors_db_url: str) -> None:
    logger.info("re-ingesting SA-512-0 into %s", SWEEP_TABLE)
    manifest_path = data_dir / "articles.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    articles = manifest["articles"]

    all_chunks: list[Chunk] = []
    for article in articles:
        bioc_path = data_dir / "sources" / article["category"] / article["slug"] / "article.json"
        if not bioc_path.exists():
            logger.warning("BioC JSON not found for %s; skipping", article["slug"])
            continue
        bioc_data = json.loads(bioc_path.read_text(encoding="utf-8"))
        chunks = chunk_bioc_document(
            bioc_data,
            doc_url=article["pmc_url"],
            doc_title=article["title"],
            chunk_tokens=512,
            overlap_tokens=0,
            respect_section_boundaries=True,
            skip_sections=SKIP_SECTIONS,
        )
        all_chunks.extend(chunks)

    logger.info("SA-512-0: %d chunks from %d articles", len(all_chunks), len(articles))

    embedder = ChunkEmbedder(model_name=EMBEDDING_MODEL, document_prefix=DOCUMENT_PREFIX)
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
    embedder: ChunkEmbedder,
    vectors_db_url: str,
) -> dict[str, list[dict]]:
    results: dict[str, list[dict]] = {}
    for cond_id, cond in CONDITIONS.items():
        logger.info("retrieving for condition %s (table=%s)", cond_id, cond["table"])
        cond_results = []
        for i, q in enumerate(questions):
            query_vec = embedder._model.encode(
                [q["question"]],
                convert_to_numpy=True,
                normalize_embeddings=True,
                show_progress_bar=False,
            )[0]
            query_vec = np.array(query_vec, dtype=np.float32)
            hits = _retrieve_from_table(cond["table"], query_vec, vectors_db_url, TOP_K)
            cond_results.append(
                {
                    "query_id": q["id"],
                    "question": q["question"],
                    "reference_answer": q["answer"],
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
        model_name="NeuML/pubmedbert-base-embeddings",
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
        _reingest_sa512(args.data_dir, args.vectors_db_url)

    logger.info("loading embedding model %s", EMBEDDING_MODEL)
    embedder = ChunkEmbedder(model_name=EMBEDDING_MODEL, document_prefix=DOCUMENT_PREFIX)

    logger.info("stage 1: retrieve")
    retrieval = _stage_retrieve(questions, embedder, args.vectors_db_url)

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
        help=f"Path to pubmed-hypertension data source. Default: {DEFAULT_DATA_DIR}",
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
        help="Skip re-ingestion of SA-512-0 into sweep table.",
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
