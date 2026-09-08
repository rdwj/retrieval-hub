"""Ontology-assisted vs. raw retrieval benchmark.

Runs paired retrieval queries two ways — with and without ontology
assistance — and measures the difference in hit count, source coverage,
and recall. No LLM involved; all metrics are deterministic.

Uses direct DB access for ontology queries and the retrieval_hub API
for vector search (no MCP client connection needed).

Usage:
    python scripts/eval_ontology_benchmark.py --db-url postgresql+psycopg://...
    python scripts/eval_ontology_benchmark.py --query-id xsrc-01
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import create_engine, func, or_, select, text
from sqlalchemy.orm import Session, sessionmaker

from retrieval_hub.models.ontology import OntologyMapping
from retrieval_hub.models.ontology_concept import (
    OntologyConcept as OntologyConceptModel,
)
from retrieval_hub.models.ontology_relationship import (
    OntologyRelationship as OntologyRelationshipModel,
)
import retrieval_hub.retrieval.api as _retrieval_api
from retrieval_hub.adapters.base import SourceAdapter
from retrieval_hub.retrieval.api import query as retrieval_query

logger = logging.getLogger("eval_ontology_benchmark")

REPO_ROOT = Path(__file__).resolve().parent.parent
EVAL_DIR = REPO_ROOT / "eval" / "ontology_benchmark"
QUERY_SET_PATH = EVAL_DIR / "query_set.json"

DEFAULT_DB_URL = (
    "postgresql+psycopg://retrievalhub:retrievalhub@127.0.0.1:5434/retrievalhub"
)
DEFAULT_VECTORS_DB_URL = (
    "postgresql+psycopg://retrievalhub:retrievalhub"
    "@127.0.0.1:5434/retrievalhub_vectors"
)
DEFAULT_EMBEDDING_URL = "http://127.0.0.1:8081"


# ---------------------------------------------------------------------------
# Ontology queries (direct DB)
# ---------------------------------------------------------------------------


def describe_ontology_db(
    session: Session,
    concept: str | None = None,
    include_hierarchy: bool = False,
    include_relationships: bool = False,
) -> dict:
    """Replicate describe_ontology logic via direct DB queries."""
    stmt = select(OntologyMapping)
    if concept:
        stmt = stmt.where(
            func.lower(OntologyMapping.canonical_name) == concept.lower()
        )
    stmt = stmt.order_by(
        OntologyMapping.canonical_name,
        OntologyMapping.authority_score.desc(),
    )
    mappings = session.execute(stmt).scalars().all()

    grouped: dict[str, list[dict]] = {}
    for m in mappings:
        grouped.setdefault(m.canonical_name, []).append({
            "source_slug": m.source_slug,
            "local_name": m.local_name,
            "authority_score": m.authority_score,
        })

    concepts = []
    for name, source_mappings in grouped.items():
        entry: dict = {
            "canonical_name": name,
            "source_mappings": source_mappings,
        }

        if include_hierarchy:
            row = session.execute(
                select(OntologyConceptModel).where(
                    OntologyConceptModel.name == name
                )
            ).scalar_one_or_none()
            entry["parent"] = row.parent_name if row else None
            children_rows = session.execute(
                select(OntologyConceptModel.name).where(
                    OntologyConceptModel.parent_name == name
                )
            ).scalars().all()
            entry["children"] = list(children_rows)

        if include_relationships:
            rels = session.execute(
                select(OntologyRelationshipModel).where(
                    or_(
                        func.lower(
                            OntologyRelationshipModel.source_concept
                        ) == name.lower(),
                        func.lower(
                            OntologyRelationshipModel.target_concept
                        ) == name.lower(),
                    )
                )
            ).scalars().all()
            entry["relationships"] = [
                {
                    "source_concept": r.source_concept,
                    "relationship": r.relationship,
                    "target_concept": r.target_concept,
                    "source_slug": r.source_slug,
                }
                for r in rels
            ]

        concepts.append(entry)

    return {
        "concepts": concepts,
        "total_concepts": len(concepts),
        "total_mappings": len(mappings),
    }


# ---------------------------------------------------------------------------
# Retrieval wrapper
# ---------------------------------------------------------------------------


def do_retrieve(
    db_session: Session,
    query_text: str,
    source_slug: str,
    top_k: int = 5,
    doc_section: list[str] | None = None,
    vectors_db_url: str = DEFAULT_VECTORS_DB_URL,
    raw: bool = False,
) -> list[dict]:
    """Call retrieval_hub.retrieval.api.query and return normalized hits.

    When ``raw=True``, the retrieval API's built-in ontology expansion
    is bypassed so the doc_section filter is applied literally.
    """
    if raw:
        _retrieval_api.expand_doc_section_via_registry = (
            lambda _sess, _slug, ds: ds
        )
        SourceAdapter._expand_doc_section = lambda _self, ds: ds
    try:
        results = retrieval_query(
            source_slug=source_slug,
            query_text=query_text,
            session=db_session,
            top_k=top_k,
            vectors_db_url=vectors_db_url,
            doc_section=doc_section,
        )
        return [
            {
                "chunk_id": str(r.chunk_id),
                "doc_title": r.doc_title,
                "doc_section": r.doc_section,
                "score": r.score,
                "source": r.source_slug,
            }
            for r in results
        ]
    except Exception as exc:
        logger.warning(
            "retrieve(%s, %s, doc_section=%s) failed: %s",
            source_slug, query_text[:40], doc_section, exc,
        )
        return []
    finally:
        if raw:
            _retrieval_api.expand_doc_section_via_registry = (
                _retrieval_api._orig_expand
            )
            SourceAdapter._expand_doc_section = (
                SourceAdapter._orig_expand_section
            )


# ---------------------------------------------------------------------------
# Hit summarization
# ---------------------------------------------------------------------------


def summarize_hits(hits: list[dict]) -> dict:
    sources: dict[str, int] = {}
    for h in hits:
        src = h.get("source", "unknown")
        sources[src] = sources.get(src, 0) + 1

    scores = [h["score"] for h in hits if h.get("score")]
    return {
        "total_hits": len(hits),
        "sources_with_hits": len(sources),
        "hits_per_source": sources,
        "mean_score": sum(scores) / len(scores) if scores else 0.0,
        "hits": hits,
    }


# ---------------------------------------------------------------------------
# Dimension runners
# ---------------------------------------------------------------------------


def run_cross_source(
    db_session: Session, q: dict, top_k: int, vectors_db_url: str,
) -> dict:
    concept = q["concept"]
    query_text = q["query_text"]
    sources = q["sources"]

    onto = describe_ontology_db(db_session, concept=concept)
    with_hits: list[dict] = []
    if onto["concepts"]:
        info = onto["concepts"][0]
        for src_slug in sources:
            src_mappings = [
                m for m in info["source_mappings"]
                if m["source_slug"] == src_slug
            ]
            if not src_mappings:
                continue
            local_names = [m["local_name"] for m in src_mappings]
            avg_auth = sum(
                m["authority_score"] for m in src_mappings
            ) / len(src_mappings)
            hits = do_retrieve(
                db_session, query_text, src_slug, top_k,
                doc_section=local_names, vectors_db_url=vectors_db_url,
            )
            for h in hits:
                h["authority_score"] = avg_auth
            with_hits.extend(hits)

    without_hits: list[dict] = []
    for src_slug in sources:
        hits = do_retrieve(
            db_session, query_text, src_slug, top_k,
            doc_section=[concept], vectors_db_url=vectors_db_url,
            raw=True,
        )
        without_hits.extend(hits)

    return _build_result(q, "cross_source", with_hits, without_hits)


def run_hierarchy(
    db_session: Session, q: dict, top_k: int, vectors_db_url: str,
) -> dict:
    concept = q["concept"]
    query_text = q["query_text"]
    child_top_k = min(top_k, 3)

    onto = describe_ontology_db(
        db_session, concept=concept, include_hierarchy=True,
    )
    with_hits: list[dict] = []
    if onto["concepts"]:
        children = onto["concepts"][0].get("children") or []
        for child in children:
            child_onto = describe_ontology_db(db_session, concept=child)
            if not child_onto["concepts"]:
                continue
            for mapping in child_onto["concepts"][0]["source_mappings"]:
                hits = do_retrieve(
                    db_session, query_text, mapping["source_slug"],
                    child_top_k, doc_section=[mapping["local_name"]],
                    vectors_db_url=vectors_db_url,
                )
                with_hits.extend(hits)

    without_hits: list[dict] = []
    for src_slug in q.get("sources", []):
        hits = do_retrieve(
            db_session, query_text, src_slug, top_k,
            vectors_db_url=vectors_db_url, raw=True,
        )
        without_hits.extend(hits)

    return _build_result(q, "hierarchy", with_hits, without_hits)


def run_relationship(
    db_session: Session, q: dict, top_k: int, vectors_db_url: str,
) -> dict:
    start_concept = q["start_concept"]
    target_concept = q["target_concept"]
    query_text = q["query_text"]

    onto = describe_ontology_db(
        db_session, concept=start_concept, include_relationships=True,
    )
    with_hits: list[dict] = []

    if onto["concepts"]:
        for mapping in onto["concepts"][0]["source_mappings"]:
            hits = do_retrieve(
                db_session, query_text, mapping["source_slug"],
                top_k, doc_section=[mapping["local_name"]],
                vectors_db_url=vectors_db_url,
            )
            with_hits.extend(hits)

    target_onto = describe_ontology_db(db_session, concept=target_concept)
    if target_onto["concepts"]:
        for mapping in target_onto["concepts"][0]["source_mappings"]:
            hits = do_retrieve(
                db_session, query_text, mapping["source_slug"],
                top_k, doc_section=[mapping["local_name"]],
                vectors_db_url=vectors_db_url,
            )
            with_hits.extend(hits)

    without_hits: list[dict] = []
    for src_slug in q.get("start_sources", q.get("sources", [])):
        hits = do_retrieve(
            db_session, query_text, src_slug, top_k,
            vectors_db_url=vectors_db_url, raw=True,
        )
        without_hits.extend(hits)

    return _build_result(q, "relationship", with_hits, without_hits)


def _build_result(
    q: dict, dimension: str,
    with_hits: list[dict], without_hits: list[dict],
) -> dict:
    w = summarize_hits(with_hits)
    wo = summarize_hits(without_hits)

    w_total = w["total_hits"]
    wo_total = wo["total_hits"]
    hit_lift = w_total - wo_total
    src_lift = w["sources_with_hits"] - wo["sources_with_hits"]
    recall_lift = (w_total - wo_total) / w_total if w_total > 0 else 0.0
    score_delta = w["mean_score"] - wo["mean_score"]

    return {
        "id": q.get("id", "unknown"),
        "dimension": dimension,
        "concept": q.get("concept", q.get("start_concept", "")),
        "with_ontology": w,
        "without_ontology": wo,
        "metrics": {
            "hit_count_lift": hit_lift,
            "source_coverage_lift": src_lift,
            "recall_lift": round(recall_lift, 4),
            "mean_score_delta": round(score_delta, 4),
        },
    }


DIMENSION_RUNNERS = {
    "cross_source": run_cross_source,
    "hierarchy": run_hierarchy,
    "relationship": run_relationship,
}


# ---------------------------------------------------------------------------
# Aggregation
# ---------------------------------------------------------------------------


def aggregate_by_dimension(results: list[dict]) -> dict:
    dims: dict[str, list[dict]] = {}
    for r in results:
        dims.setdefault(r["dimension"], []).append(r)

    summaries = {}
    for dim, queries in sorted(dims.items()):
        lifts = [q["metrics"]["hit_count_lift"] for q in queries]
        src_lifts = [q["metrics"]["source_coverage_lift"] for q in queries]
        recall_lifts = [q["metrics"]["recall_lift"] for q in queries]
        wins = sum(1 for q in queries if q["metrics"]["hit_count_lift"] > 0)
        summaries[dim] = {
            "dimension": dim,
            "query_count": len(queries),
            "mean_hit_count_lift": round(_mean(lifts), 2),
            "mean_source_coverage_lift": round(_mean(src_lifts), 2),
            "mean_recall_lift": round(_mean(recall_lifts), 4),
            "queries_where_ontology_wins": wins,
            "win_rate": round(wins / len(queries), 4) if queries else 0.0,
        }

    all_lifts = [q["metrics"]["hit_count_lift"] for q in results]
    all_src = [q["metrics"]["source_coverage_lift"] for q in results]
    all_recall = [q["metrics"]["recall_lift"] for q in results]
    all_wins = sum(1 for q in results if q["metrics"]["hit_count_lift"] > 0)
    summaries["overall"] = {
        "dimension": "overall",
        "query_count": len(results),
        "mean_hit_count_lift": round(_mean(all_lifts), 2),
        "mean_source_coverage_lift": round(_mean(all_src), 2),
        "mean_recall_lift": round(_mean(all_recall), 4),
        "queries_where_ontology_wins": all_wins,
        "win_rate": round(all_wins / len(results), 4) if results else 0.0,
    }
    return summaries


def compute_authority_correlation(results: list[dict]) -> dict:
    pairs: list[tuple[float, float]] = []
    for r in results:
        if r["dimension"] != "cross_source":
            continue
        for hit in r["with_ontology"].get("hits", []):
            auth = hit.get("authority_score")
            score = hit.get("score")
            if auth is not None and score is not None:
                pairs.append((auth, score))

    if len(pairs) < 3:
        return {"note": "Insufficient data for correlation (need >= 3 pairs)"}

    try:
        from scipy.stats import spearmanr
        auth_scores, sim_scores = zip(*pairs)
        corr, pvalue = spearmanr(auth_scores, sim_scores)
        return {"r": round(corr, 4), "p": round(pvalue, 4), "n": len(pairs)}
    except ImportError:
        return {"note": "N/A - scipy not available"}


def _mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------

DIM_DISPLAY = {
    "cross_source": "Cross-source",
    "hierarchy": "Hierarchy",
    "relationship": "Relationship",
    "overall": "Overall",
}


def _fmt_sign(val: float) -> str:
    return f"+{val}" if val >= 0 else str(val)


def _fmt_row(label: str, s: dict) -> str:
    return (
        f"{label:<22}{s['query_count']:>7}"
        f"  {s['win_rate'] * 100:>7.1f}%"
        f"  {_fmt_sign(round(s['mean_hit_count_lift'], 1)):>12}"
        f"  {_fmt_sign(round(s['mean_source_coverage_lift'], 1)):>15}"
        f"  {s['mean_recall_lift']:>15.3f}"
    )


def generate_report(
    summaries: dict, results: list[dict], config: dict,
    authority_corr: dict,
) -> str:
    header = (
        f"{'Dimension':<22}{'Queries':>7}  {'Win Rate':>8}  {'Avg Hit Lift':>12}"
        f"  {'Avg Source Lift':>15}  {'Avg Recall Lift':>15}"
    )
    sep = "-" * 22 + "  " + "-" * 7 + "  " + "-" * 8 + "  " + "-" * 12 \
        + "  " + "-" * 15 + "  " + "-" * 15
    lines = [
        "Ontology-Assisted vs. Raw Retrieval Benchmark",
        "=" * 46,
        f"Run: {config['timestamp']}",
        f"DB: {config['db_url'].split('@')[1] if '@' in config['db_url'] else config['db_url']}",
        f"Queries: {config['query_count']} | top_k: {config['top_k']}",
        "", header, sep,
    ]

    for dim in ["cross_source", "hierarchy", "relationship"]:
        if dim in summaries:
            lines.append(_fmt_row(DIM_DISPLAY.get(dim, dim), summaries[dim]))

    lines.append(sep)
    if "overall" in summaries:
        lines.append(_fmt_row("Overall", summaries["overall"]))

    lines.append("")
    if "r" in authority_corr:
        lines.append(
            f"Authority Score Correlation: r={authority_corr['r']}, "
            f"p={authority_corr['p']} (n={authority_corr['n']})"
        )
    else:
        lines.append(
            f"Authority Score Correlation: "
            f"{authority_corr.get('note', 'N/A')}"
        )

    lines.append("")
    lines.append("Per-Query Results:")
    for r in results:
        w = r["with_ontology"]
        wo = r["without_ontology"]
        lift = r["metrics"]["hit_count_lift"]
        concept = r.get("concept", "")
        lines.append(
            f"  {r['id']:<10} {concept:<28}: "
            f"with={w['total_hits']:>3} hits ({w['sources_with_hits']} src)  "
            f"without={wo['total_hits']:>3} hits ({wo['sources_with_hits']} src)  "
            f"lift={'+' if lift >= 0 else ''}{lift}"
        )
    lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def run_benchmark(args: argparse.Namespace) -> int:
    if not QUERY_SET_PATH.exists():
        logger.error("Query set not found: %s", QUERY_SET_PATH)
        return 1

    query_set = json.loads(QUERY_SET_PATH.read_text(encoding="utf-8"))
    queries = query_set.get("queries", [])

    if args.query_id:
        queries = [q for q in queries if q.get("id") == args.query_id]
        if not queries:
            logger.error("No query found with id=%s", args.query_id)
            return 1

    logger.info("Loaded %d query(ies)", len(queries))

    run_id = datetime.now(tz=timezone.utc).strftime("%Y%m%d-%H%M%S")
    output_dir = (
        Path(args.output_dir) if args.output_dir
        else EVAL_DIR / "runs" / run_id
    )
    output_dir.mkdir(parents=True, exist_ok=True)

    # Override the embedding endpoint resolver so queries use the
    # local port-forward rather than the cluster-internal URL.
    def _local_resolve(*_args, **_kwargs):
        return args.embedding_url

    _retrieval_api._resolve_embedding_endpoint = _local_resolve

    # Save the real ontology expansion functions. The "without ontology"
    # path disables both the registry-level and adapter-level expansion
    # to simulate a retrieval stack with no ontology layer (the raw
    # doc_section filter is applied literally).
    _retrieval_api._orig_expand = (
        _retrieval_api.expand_doc_section_via_registry
    )
    SourceAdapter._orig_expand_section = SourceAdapter._expand_doc_section

    engine = create_engine(args.db_url)
    session_factory = sessionmaker(bind=engine)

    with session_factory() as db_session:
        # Verify ontology data exists.
        count = db_session.execute(
            text("SELECT COUNT(*) FROM ontology_mapping")
        ).scalar()
        logger.info("Ontology has %d mappings", count)
        if count == 0:
            logger.error("No ontology mappings found — is the DB correct?")
            return 1

        results: list[dict] = []
        start = time.monotonic()

        for i, q in enumerate(queries, 1):
            dim = q.get("dimension", "cross_source")
            runner = DIMENSION_RUNNERS.get(dim)
            if not runner:
                logger.warning(
                    "Unknown dimension %r for %s, skipping",
                    dim, q.get("id"),
                )
                continue

            logger.info(
                "[%d/%d] %s: %s", i, len(queries), dim, q.get("id"),
            )
            result = runner(
                db_session, q, args.top_k, args.vectors_db_url,
            )
            results.append(result)

        elapsed = time.monotonic() - start
        logger.info("Completed %d queries in %.1fs", len(results), elapsed)

    summaries = aggregate_by_dimension(results)
    authority_corr = compute_authority_correlation(results)

    config = {
        "db_url": args.db_url,
        "vectors_db_url": args.vectors_db_url,
        "top_k": args.top_k,
        "timestamp": datetime.now(tz=timezone.utc).isoformat(),
        "query_count": len(results),
        "total_sources": len({
            src
            for r in results
            for src in r["with_ontology"]["hits_per_source"]
        }),
        "elapsed_seconds": round(elapsed, 2),
    }

    (output_dir / "config.json").write_text(
        json.dumps(config, indent=2) + "\n", encoding="utf-8",
    )
    (output_dir / "results.json").write_text(
        json.dumps(results, indent=2) + "\n", encoding="utf-8",
    )

    summary_data = {
        "dimensions": summaries,
        "authority_correlation": authority_corr,
    }
    (output_dir / "summary.json").write_text(
        json.dumps(summary_data, indent=2) + "\n", encoding="utf-8",
    )

    report = generate_report(summaries, results, config, authority_corr)
    (output_dir / "report.txt").write_text(report, encoding="utf-8")

    print(report)
    logger.info("Results written to %s", output_dir)
    return 0


def main():
    parser = argparse.ArgumentParser(
        description="Ontology-assisted vs. raw retrieval benchmark",
    )
    parser.add_argument(
        "--db-url", default=DEFAULT_DB_URL,
        help="Catalog DB URL (default: %(default)s)",
    )
    parser.add_argument(
        "--vectors-db-url", default=DEFAULT_VECTORS_DB_URL,
        help="Vectors DB URL (default: %(default)s)",
    )
    parser.add_argument(
        "--top-k", type=int, default=5,
        help="Results per retrieve call (default: %(default)s)",
    )
    parser.add_argument(
        "--embedding-url", default=DEFAULT_EMBEDDING_URL,
        help="Embedding service URL (default: %(default)s)",
    )
    parser.add_argument("--query-id", help="Run a single query by ID")
    parser.add_argument("--output-dir", help="Override output directory")
    parser.add_argument(
        "--verbose", "-v", action="store_true",
        help="Enable debug logging",
    )

    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )

    sys.exit(run_benchmark(args))


if __name__ == "__main__":
    main()
