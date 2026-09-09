"""Ontology health audit CLI.

Runs all ontology health checks against the catalog database, formats
findings as a console report or JSON, and optionally applies safe fixes
(exact-match missing mappings and authority score recomputation).

Usage:
    python scripts/ontology_doctor.py
    python scripts/ontology_doctor.py --source va-cpg --skip-retrieval
    python scripts/ontology_doctor.py --json report.json --verbose
    python scripts/ontology_doctor.py --apply --skip-retrieval
"""

from __future__ import annotations

import argparse
import json
import logging
from datetime import UTC, datetime

from sqlalchemy import create_engine, func
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import sessionmaker

from retrieval_hub.models.ontology import OntologyMapping
from retrieval_hub.models.ontology_concept import (
    OntologyConcept as OntologyConceptModel,
)
from retrieval_hub.ontology.authority import compute_authority_scores
from retrieval_hub.ontology.doctor import (
    check_coverage_gaps,
    check_dangling_relationships,
    check_dead_mappings,
    check_duplicate_mappings,
    check_family_mismatches,
    check_missing_mappings,
    check_orphan_concepts,
    check_score_clustering,
    check_stale_mappings,
)

logger = logging.getLogger("ontology_doctor")

DEFAULT_DB_URL = (
    "postgresql+psycopg://retrievalhub:retrievalhub@127.0.0.1:5434/retrievalhub"
)
DEFAULT_VECTORS_DB_URL = (
    "postgresql+psycopg://retrievalhub:retrievalhub"
    "@127.0.0.1:5434/retrievalhub_vectors"
)
DEFAULT_EMBEDDING_URL = "http://127.0.0.1:8081"

CHECK_ORDER = [
    ("missing_mappings", "Missing Mappings"),
    ("stale_mappings", "Stale Mappings"),
    ("family_mismatches", "Family Mismatches"),
    ("score_clustering", "Score Clustering"),
    ("coverage_gaps", "Coverage Gaps"),
    ("dead_mappings", "Dead Mappings"),
    ("duplicate_mappings", "Duplicate Mappings"),
    ("orphan_concepts", "Orphan Concepts"),
    ("dangling_relationships", "Dangling Relationships"),
]


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Audit ontology health.")
    p.add_argument("--db-url", default=DEFAULT_DB_URL,
                   help="Catalog DB (default: %(default)s)")
    p.add_argument("--vectors-db-url", default=DEFAULT_VECTORS_DB_URL,
                   help="Vectors DB (default: %(default)s)")
    p.add_argument("--embedding-url", default=DEFAULT_EMBEDDING_URL,
                   help="Embedding service (default: %(default)s)")
    p.add_argument("--source", default=None, metavar="SLUG",
                   help="Audit single source only")
    p.add_argument("--concept", default=None, metavar="NAME",
                   help="Audit single concept (score clustering)")
    p.add_argument("--skip-retrieval", action="store_true",
                   help="Skip dead mapping check")
    p.add_argument("--apply", action="store_true",
                   help="Apply safe fixes (exact-match mappings + rescore)")
    p.add_argument("--json", default=None, metavar="FILE", dest="json_file",
                   help="Write JSON report to FILE")
    p.add_argument("--include-retired", action="store_true",
                   help="Include RETIRED sources")
    p.add_argument("--verbose", action="store_true", help="Debug logging")
    return p


def _run(name: str, fn, *a, **kw) -> list[dict]:
    logger.info("Running %s...", name)
    return fn(*a, **kw)


def run_checks(session, args) -> dict[str, list[dict]]:
    """Run all checks and return findings grouped by check name."""
    src = args.source
    r: dict[str, list[dict]] = {
        "missing_mappings": _run("missing_mappings", check_missing_mappings,
                                 session, source_slug=src,
                                 include_retired=args.include_retired),
        "stale_mappings": _run("stale_mappings", check_stale_mappings,
                               session, source_slug=src,
                               vectors_db_url=args.vectors_db_url),
        "family_mismatches": _run("family_mismatches",
                                  check_family_mismatches, session),
        "score_clustering": _run("score_clustering", check_score_clustering,
                                 session, concept_name=args.concept),
        "coverage_gaps": _run("coverage_gaps", check_coverage_gaps, session),
    }
    if args.skip_retrieval:
        logger.info("Skipping dead_mappings (--skip-retrieval)")
        r["dead_mappings"] = []
    else:
        r["dead_mappings"] = _run("dead_mappings", check_dead_mappings,
                                  session, source_slug=src,
                                  vectors_db_url=args.vectors_db_url,
                                  embedding_url=args.embedding_url)
    r["duplicate_mappings"] = _run("duplicate_mappings",
                                   check_duplicate_mappings,
                                   session, source_slug=src)
    r["orphan_concepts"] = _run("orphan_concepts",
                                check_orphan_concepts, session)
    r["dangling_relationships"] = _run("dangling_relationships",
                                       check_dangling_relationships, session)
    return r


def compute_summary(session, results: dict[str, list[dict]]) -> dict[str, int]:
    """Compute aggregate counts for the report header."""
    concepts = session.query(func.count(OntologyConceptModel.name)).scalar() or 0
    mappings = session.query(func.count(OntologyMapping.id)).scalar() or 0
    slugs: set[str] = {
        f["source_slug"] for fs in results.values() for f in fs
        if "source_slug" in f
    } | {row[0] for row in session.query(OntologyMapping.source_slug).distinct()}
    all_findings = [f for fs in results.values() for f in fs]
    warn = sum(1 for f in all_findings if f.get("severity") == "WARN")
    return {
        "sources_checked": len(slugs), "concepts_checked": concepts,
        "mappings_checked": mappings, "warn_count": warn,
        "info_count": len(all_findings) - warn,
    }


def _fmt_finding(check: str, f: dict) -> list[str]:
    """Return indented lines for a single finding."""
    sev = f.get("severity", "INFO")
    if check == "missing_mappings":
        total = f['total_entities']
        unmapped_n = len(f['unmapped'])
        mapped_n = total - unmapped_n
        return [
            f"  {f['source_slug']}: {mapped_n} of {total} entities mapped "
            f"({f['mapped_count']} mapping rows) [{sev}]",
            f"    Unmapped: {', '.join(f['unmapped'])}",
        ]
    if check == "stale_mappings":
        return [
            f"  {f['source_slug']}: {f['canonical_name']} -> "
            f"{f['local_name']} [{sev}]",
            f"    Reason: {f['reason']}",
        ]
    if check == "family_mismatches":
        return [
            f"  {f['canonical_name']}: graph={f['graph_sources']}, "
            f"doc={f['document_sources']} [{sev}]",
        ]
    if check == "score_clustering":
        issue = f["issue"]
        if issue == "narrow_range":
            return [
                f"  Range: {f['min_score']:.3f} - {f['max_score']:.3f} "
                f"(spread: {f['spread']:.3f}) [{sev}: < 0.3]",
            ]
        if issue == "shared_max":
            return [
                f"  {len(f['concepts_at_max'])} concepts share max score "
                f"{f['max_score']:.3f} [{sev}]",
            ]
        return [
            f"  {f['canonical_name']}: {f['mapping_count']} mappings all at "
            f"score {f['score']:.3f} [{sev}]",
        ]
    if check == "coverage_gaps":
        return [
            f"  {f['canonical_name']} ({f['family']}): "
            f"mapped={f['mapped_sources']}, "
            f"unmapped={f['unmapped_sources']} [{sev}]",
        ]
    if check == "dead_mappings":
        return [
            f"  {f['source_slug']}: {f['canonical_name']} -> "
            f"{f['local_name']} ({f['hit_count']} hits) [{sev}]",
        ]
    if check == "duplicate_mappings":
        return [
            f"  {f['source_slug']}: {f['canonical_name']} -> "
            f"{f['local_names']} [{sev}]",
        ]
    if check == "orphan_concepts":
        parent = f.get("parent_name") or "(root)"
        return [f"  {f['concept_name']} (parent: {parent}) [{sev}]"]
    if check == "dangling_relationships":
        return [
            f"  {f['source_concept']} --[{f['relationship']}]--> "
            f"{f['target_concept']} (dangling: {f['dangling_end']}) [{sev}]",
        ]
    return [f"  {f}"]


def print_console_report(
    results: dict[str, list[dict]],
    summary: dict[str, int],
    *,
    skip_retrieval: bool = False,
) -> None:
    """Print a human-readable report to stdout."""
    print("\nOntology Health Report")
    print("======================")
    print(
        f"Checked: {summary['sources_checked']} sources, "
        f"{summary['concepts_checked']} concepts, "
        f"{summary['mappings_checked']} mappings\n")

    for name, label in CHECK_ORDER:
        findings = results.get(name, [])

        if name == "missing_mappings":
            suffix = f"({len(findings)} sources with gaps)"
        elif name == "dead_mappings" and skip_retrieval:
            suffix = "(skipped: --skip-retrieval)"
        else:
            suffix = f"({len(findings)} found)"

        header = f"{label} {suffix}"
        print(header)
        print("-" * len(header))

        if name == "dead_mappings" and skip_retrieval:
            print("  (skipped)")
        elif not findings:
            print("  (none)")
        else:
            for f in findings:
                for line in _fmt_finding(name, f):
                    print(line)
        print()

    print(f"Summary: {summary['warn_count']} WARN, {summary['info_count']} INFO\n")


def write_json_report(
    results: dict[str, list[dict]], summary: dict[str, int], path: str,
) -> None:
    """Write structured JSON report to a file."""
    report = {
        "timestamp": datetime.now(UTC).isoformat(),
        "checks": {name: results.get(name, []) for name, _ in CHECK_ORDER},
        "summary": summary,
    }
    with open(path, "w") as fh:
        json.dump(report, fh, indent=2, default=str)
    logger.info("JSON report written to %s", path)


def apply_fixes(session, results: dict[str, list[dict]]) -> None:
    """Apply exact-match missing mappings and recompute authority scores."""
    missing = results.get("missing_mappings", [])
    if not missing:
        print("No missing mappings to fix.")
        return

    canonical_lookup: dict[str, str] = {
        row.name.lower(): row.name
        for row in session.query(OntologyConceptModel.name)
    }

    added = 0
    manual: list[tuple[str, str]] = []

    for finding in missing:
        slug = finding["source_slug"]
        for entity_type in finding["unmapped"]:
            canonical = canonical_lookup.get(entity_type.lower())
            if canonical is None:
                manual.append((slug, entity_type))
                continue
            stmt = pg_insert(OntologyMapping).values(
                canonical_name=canonical, source_slug=slug,
                local_name=entity_type, authority_score=1.0,
            ).on_conflict_do_nothing(
                constraint="uq_ontology_mapping_canonical_source_local")
            result = session.execute(stmt)
            if result.rowcount > 0:
                added += 1
                print(f"  Added: {slug} / {entity_type} -> {canonical}")
            else:
                print(f"  Already exists: {slug} / {entity_type} -> {canonical}")

    print("\nRecomputing authority scores...")
    scores = compute_authority_scores(session)
    for mid, score in scores:
        session.query(OntologyMapping).filter(
            OntologyMapping.id == mid).update({"authority_score": score})
    session.commit()
    print(f"  Updated {len(scores)} mapping scores.\n")
    print(f"Applied: {added} new mappings added.")
    if manual:
        print(f"Skipped: {len(manual)} entity types need manual mapping:")
        for s, et in manual:
            print(f"  {s} / {et}")


def main() -> None:
    args = build_parser().parse_args()
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)-5s %(name)s: %(message)s",
    )

    make_session = sessionmaker(bind=create_engine(args.db_url))
    with make_session() as session:
        results = run_checks(session, args)
        summary = compute_summary(session, results)

        if args.json_file:
            write_json_report(results, summary, args.json_file)
        else:
            print_console_report(
                results, summary, skip_retrieval=args.skip_retrieval)

        if args.apply:
            print("Applying safe fixes...")
            apply_fixes(session, results)


if __name__ == "__main__":
    main()
