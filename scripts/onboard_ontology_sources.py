#!/usr/bin/env python3
"""Onboard sources to the ontology registry.

Sets semantic_context on each source, creates new ontology concepts where
needed, adds ontology mappings, and recomputes authority scores.

Usage:
    python scripts/onboard_ontology_sources.py
    python scripts/onboard_ontology_sources.py --dry-run --verbose
    python scripts/onboard_ontology_sources.py --db-url postgresql+psycopg://...
"""

from __future__ import annotations

import argparse
import logging

from sqlalchemy import create_engine
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import sessionmaker

from retrieval_hub.models import Source
from retrieval_hub.models.ontology import OntologyMapping
from retrieval_hub.models.ontology_concept import OntologyConcept
from retrieval_hub.ontology.authority import compute_authority_scores

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

DEFAULT_DB_URL = (
    "postgresql+psycopg://retrievalhub:retrievalhub@127.0.0.1:5434/retrievalhub"
)

# -- Source definitions -------------------------------------------------------

_PUBMED_SC = {
    "entities": [
        {
            "name": "Hypertension", "entity_type": "condition",
            "definition": "Primary focus of this collection -- management, diagnosis, and treatment of elevated blood pressure.",
            "aliases": ["high blood pressure", "HTN", "elevated blood pressure"],
        },
        {
            "name": "Pharmacotherapy", "entity_type": "treatment",
            "definition": "Drug-based treatments for hypertension including ACE inhibitors, ARBs, CCBs, and diuretics.",
            "aliases": ["antihypertensive drugs", "medication therapy", "drug treatment"],
        },
        {
            "name": "Comorbidity", "entity_type": "condition",
            "definition": "Conditions frequently co-occurring with hypertension: diabetes, kidney disease, cardiovascular disease.",
            "aliases": ["comorbid condition", "co-existing disease"],
        },
        {
            "name": "Lifestyle Intervention", "entity_type": "treatment",
            "definition": "Non-pharmacological approaches: diet, exercise, salt restriction, weight management.",
            "aliases": ["lifestyle modification", "behavioral intervention"],
        },
    ],
    "domain_context": (
        "Open-access PubMed Central review articles on hypertension management, "
        "covering guidelines, pharmacotherapy, lifestyle, adherence, and comorbidities."
    ),
    "abbreviations": {
        "HTN": "hypertension", "SBP": "systolic blood pressure",
        "DBP": "diastolic blood pressure", "ACE": "angiotensin-converting enzyme",
        "ARB": "angiotensin receptor blocker", "CCB": "calcium channel blocker",
    },
}

_AIRCRAFT_SC = {
    "entities": [
        {
            "name": "Service Bulletin", "entity_type": "document_type",
            "definition": "Mandatory or recommended maintenance action issued by the manufacturer for specific aircraft models and serial numbers.",
            "aliases": ["SB", "bulletin"],
        },
        {
            "name": "Service Letter", "entity_type": "document_type",
            "definition": "Advisory communication from the manufacturer about maintenance best practices or product updates.",
            "aliases": ["SL", "letter"],
        },
        {
            "name": "Aircraft Component", "entity_type": "part",
            "definition": "Physical part, assembly, or system referenced in maintenance documents: engines, alternators, propellers, landing gear.",
            "aliases": ["part", "assembly", "component"],
        },
        {
            "name": "Maintenance Procedure", "entity_type": "procedure",
            "definition": "Step-by-step instructions for inspection, repair, replacement, or overhaul of aircraft components.",
            "aliases": ["procedure", "instructions", "work instructions"],
        },
    ],
    "domain_context": (
        "Piper Aircraft service bulletins, service letters, and vendor service "
        "publications for Cherokee (PA-28) and Saratoga (PA-32) aircraft families."
    ),
    "abbreviations": {
        "SB": "Service Bulletin", "SL": "Service Letter",
        "SSL": "Supplemental Service Letter", "VSP": "Vendor Service Publication",
        "CIL": "Customer Information Letter",
        "ICA": "Instructions for Continued Airworthiness",
        "AD": "Airworthiness Directive",
    },
}

_TRIALS_SC = {
    "entities": [
        {
            "name": "Clinical Trial", "entity_type": "study",
            "definition": "A registered clinical trial record from ClinicalTrials.gov, including protocol, eligibility, interventions, and outcomes.",
            "aliases": ["trial", "study", "RCT"],
        },
        {
            "name": "Intervention", "entity_type": "treatment",
            "definition": "Drug, device, or behavioral intervention being tested in the trial.",
            "aliases": ["treatment", "experimental arm", "drug"],
        },
        {
            "name": "Eligibility Criteria", "entity_type": "criteria",
            "definition": "Inclusion and exclusion criteria defining the trial's target population.",
            "aliases": ["inclusion criteria", "exclusion criteria", "enrollment criteria"],
        },
    ],
    "domain_context": (
        "ClinicalTrials.gov records for hypertension-related trials, "
        "including interventional and observational studies."
    ),
    "abbreviations": {
        "NCT": "National Clinical Trial identifier",
        "RCT": "randomized controlled trial", "BP": "blood pressure",
    },
}

_AIRCRAFT_PROCESS_SC = {
    "entities": [
        {
            "name": "Service Bulletin", "entity_type": "document_type",
            "definition": "Mandatory or recommended maintenance action, chunked with process-aware section decomposition (instructions, materials, header).",
            "aliases": ["SB", "bulletin"],
        },
        {
            "name": "Service Letter", "entity_type": "document_type",
            "definition": "Advisory communication from the manufacturer, chunked with structured sections.",
            "aliases": ["SL", "letter"],
        },
        {
            "name": "Maintenance Procedure", "entity_type": "procedure",
            "definition": "Step-by-step instructions decomposed into numbered steps, preambles, and materials lists.",
            "aliases": ["procedure", "instructions", "work instructions", "steps"],
        },
        {
            "name": "Aircraft Component", "entity_type": "part",
            "definition": "Physical part, assembly, or system referenced in maintenance documents.",
            "aliases": ["part", "assembly", "component"],
        },
    ],
    "domain_context": (
        "Piper Aircraft service bulletins and letters for Cherokee and Saratoga families, "
        "chunked with a process-aware parser that decomposes documents into structured "
        "sections: instructions/step-N, materials, header, tail."
    ),
    "abbreviations": {
        "SB": "Service Bulletin", "SL": "Service Letter",
        "SSL": "Supplemental Service Letter", "VSP": "Vendor Service Publication",
        "ICA": "Instructions for Continued Airworthiness",
        "AD": "Airworthiness Directive",
    },
}

_AIRCRAFT_TEST_SC = {
    "entities": [
        {
            "name": "Service Bulletin", "entity_type": "document_type",
            "definition": "Mandatory or recommended maintenance action for specific aircraft models and serial numbers.",
            "aliases": ["SB", "bulletin"],
        },
        {
            "name": "Service Letter", "entity_type": "document_type",
            "definition": "Advisory communication about maintenance best practices or product updates.",
            "aliases": ["SL", "letter"],
        },
        {
            "name": "Aircraft Component", "entity_type": "part",
            "definition": "Physical part, assembly, or system: engines, alternators, propellers, landing gear.",
            "aliases": ["part", "assembly", "component"],
        },
        {
            "name": "Maintenance Procedure", "entity_type": "procedure",
            "definition": "Inspection, repair, replacement, or overhaul instructions for aircraft components.",
            "aliases": ["procedure", "instructions", "work instructions"],
        },
    ],
    "domain_context": (
        "Piper Aircraft service bulletins, service letters, and vendor service "
        "publications for Cherokee (PA-28) and Saratoga (PA-32) families. "
        "Test chunking variant with 512-token chunks and 64-token overlap."
    ),
    "abbreviations": {
        "SB": "Service Bulletin", "SL": "Service Letter",
        "SSL": "Supplemental Service Letter", "VSP": "Vendor Service Publication",
        "ICA": "Instructions for Continued Airworthiness",
        "AD": "Airworthiness Directive",
    },
}

_CODE_SC = {
    "entities": [
        {
            "name": "API Endpoint", "entity_type": "api",
            "definition": "REST or MCP endpoint handler in the retrieval-hub server code.",
            "aliases": ["route", "handler", "endpoint"],
        },
        {
            "name": "Data Model", "entity_type": "model",
            "definition": "SQLAlchemy ORM model or Pydantic schema defining a database table or API contract.",
            "aliases": ["model", "schema", "table"],
        },
        {
            "name": "Adapter", "entity_type": "adapter",
            "definition": "Source adapter implementing the retrieval interface for a specific source family.",
            "aliases": ["retrieval adapter", "backend adapter"],
        },
        {
            "name": "Ingestion Pipeline", "entity_type": "pipeline",
            "definition": "Script or module that ingests, chunks, embeds, and indexes source data.",
            "aliases": ["ingest", "pipeline", "ingestion script"],
        },
    ],
    "domain_context": (
        "The retrieval-hub source code repository itself, parsed with tree-sitter "
        "AST-aware chunking at the function/class scope level."
    ),
    "abbreviations": {
        "ORM": "object-relational mapping",
        "MCP": "Model Context Protocol",
        "AST": "abstract syntax tree",
    },
}

SOURCE_DEFINITIONS: list[dict] = [
    {
        "slug": "pubmed-hypertension",
        "semantic_context": _PUBMED_SC,
        "new_concepts": [],
        "mappings": [
            {"canonical_name": "Hypertension", "local_name": "Hypertension"},
            {"canonical_name": "Compound", "local_name": "Pharmacotherapy"},
            {"canonical_name": "Condition", "local_name": "Comorbidity"},
            {"canonical_name": "Procedure", "local_name": "Lifestyle Intervention"},
        ],
    },
    {
        "slug": "aircraft-maintenance",
        "semantic_context": _AIRCRAFT_SC,
        "new_concepts": [
            {"name": "Aircraft Maintenance", "parent_name": None},
            {"name": "Service Bulletin", "parent_name": "Aircraft Maintenance"},
            {"name": "Service Letter", "parent_name": "Aircraft Maintenance"},
            {"name": "Aircraft Component", "parent_name": "Aircraft Maintenance"},
            {"name": "Maintenance Procedure", "parent_name": "Aircraft Maintenance"},
        ],
        "mappings": [
            {"canonical_name": "Service Bulletin", "local_name": "Service Bulletin"},
            {"canonical_name": "Service Letter", "local_name": "Service Letter"},
            {"canonical_name": "Aircraft Component", "local_name": "Aircraft Component"},
            {"canonical_name": "Maintenance Procedure", "local_name": "Maintenance Procedure"},
        ],
    },
    {
        "slug": "clinicaltrials-hypertension",
        "semantic_context": _TRIALS_SC,
        "new_concepts": [
            {"name": "Clinical Trial", "parent_name": None},
        ],
        "mappings": [
            {"canonical_name": "Hypertension", "local_name": "Clinical Trial"},
            {"canonical_name": "Condition", "local_name": "Eligibility Criteria"},
            {"canonical_name": "Compound", "local_name": "Intervention"},
            {"canonical_name": "Clinical Trial", "local_name": "Clinical Trial"},
        ],
    },
    {
        "slug": "aircraft-sb-process",
        "semantic_context": _AIRCRAFT_PROCESS_SC,
        "new_concepts": [],
        "mappings": [
            {"canonical_name": "Service Bulletin", "local_name": "Service Bulletin"},
            {"canonical_name": "Service Letter", "local_name": "Service Letter"},
            {"canonical_name": "Aircraft Component", "local_name": "Aircraft Component"},
            {"canonical_name": "Maintenance Procedure", "local_name": "Maintenance Procedure"},
        ],
    },
    {
        "slug": "aircraft-sb-test",
        "semantic_context": _AIRCRAFT_TEST_SC,
        "new_concepts": [],
        "mappings": [
            {"canonical_name": "Service Bulletin", "local_name": "Service Bulletin"},
            {"canonical_name": "Service Letter", "local_name": "Service Letter"},
            {"canonical_name": "Aircraft Component", "local_name": "Aircraft Component"},
            {"canonical_name": "Maintenance Procedure", "local_name": "Maintenance Procedure"},
        ],
    },
    {
        "slug": "retrieval-hub-code",
        "semantic_context": _CODE_SC,
        "new_concepts": [
            {"name": "Software", "parent_name": None},
            {"name": "API Endpoint", "parent_name": "Software"},
            {"name": "Data Model", "parent_name": "Software"},
            {"name": "Adapter", "parent_name": "Software"},
            {"name": "Ingestion Pipeline", "parent_name": "Software"},
        ],
        "mappings": [
            {"canonical_name": "API Endpoint", "local_name": "API Endpoint"},
            {"canonical_name": "Data Model", "local_name": "Data Model"},
            {"canonical_name": "Adapter", "local_name": "Adapter"},
            {"canonical_name": "Ingestion Pipeline", "local_name": "Ingestion Pipeline"},
        ],
    },
]

# -- Onboarding steps --------------------------------------------------------


def set_semantic_contexts(session, definitions: list[dict], dry_run: bool) -> int:
    """Set semantic_context on each source. Returns count of sources updated."""
    updated = 0
    for defn in definitions:
        slug = defn["slug"]
        sc = defn["semantic_context"]
        if dry_run:
            logger.info("[DRY RUN] SET semantic_context on %s", slug)
            updated += 1
            continue
        rows = (
            session.query(Source)
            .filter(Source.slug == slug)
            .update({"semantic_context": sc})
        )
        if rows:
            logger.info("SET semantic_context on %s", slug)
            updated += 1
        else:
            logger.warning("Source %s not found -- skipping semantic_context", slug)
    return updated


def create_concepts(session, definitions: list[dict], dry_run: bool) -> int:
    """Create new ontology concepts. Returns count of concepts created."""
    created = 0
    for defn in definitions:
        for concept in defn.get("new_concepts", []):
            name, parent = concept["name"], concept["parent_name"]
            if dry_run:
                logger.info("[DRY RUN] CREATE concept %s (parent: %s)", name, parent)
                created += 1
                continue
            stmt = (
                pg_insert(OntologyConcept)
                .values(name=name, parent_name=parent)
                .on_conflict_do_nothing(index_elements=["name"])
            )
            result = session.execute(stmt)
            if result.rowcount:
                logger.info("CREATE concept %s (parent: %s)", name, parent)
                created += 1
            else:
                logger.debug("Concept %s already exists -- skipped", name)
    return created


def add_mappings(session, definitions: list[dict], dry_run: bool) -> int:
    """Add ontology mappings. Returns count of mappings added."""
    added = 0
    for defn in definitions:
        slug = defn["slug"]
        for mapping in defn.get("mappings", []):
            canonical, local = mapping["canonical_name"], mapping["local_name"]
            if dry_run:
                logger.info("[DRY RUN] ADD mapping %s -> %s (source: %s)", local, canonical, slug)
                added += 1
                continue
            stmt = (
                pg_insert(OntologyMapping)
                .values(canonical_name=canonical, source_slug=slug, local_name=local)
                .on_conflict_do_nothing(constraint="uq_ontology_mapping_canonical_source_local")
            )
            result = session.execute(stmt)
            if result.rowcount:
                logger.info("ADD mapping %s -> %s (source: %s)", local, canonical, slug)
                added += 1
            else:
                logger.debug("Mapping %s -> %s (%s) already exists -- skipped", local, canonical, slug)
    return added


def recompute_scores(session, dry_run: bool) -> int:
    """Recompute authority scores and apply them. Returns count updated."""
    scores = compute_authority_scores(session)
    if not scores:
        logger.info("No mappings found -- nothing to score")
        return 0
    updated = 0
    for mapping_id, score in scores:
        if dry_run:
            logger.debug("[DRY RUN] SCORE mapping %d = %.3f", mapping_id, score)
        else:
            session.query(OntologyMapping).filter(
                OntologyMapping.id == mapping_id
            ).update({"authority_score": score})
        updated += 1
    if not dry_run:
        logger.info("Updated authority scores on %d mappings", updated)
    else:
        logger.info("[DRY RUN] Would update scores on %d mappings", updated)
    return updated


# -- Main ---------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(description="Onboard sources to the ontology registry.")
    parser.add_argument("--db-url", default=DEFAULT_DB_URL)
    parser.add_argument("--dry-run", action="store_true", help="Print actions without modifying the database.")
    parser.add_argument("--verbose", action="store_true", help="Enable debug logging.")
    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    engine = create_engine(args.db_url)
    make_session = sessionmaker(bind=engine)
    session = make_session()

    try:
        ctx_count = set_semantic_contexts(session, SOURCE_DEFINITIONS, args.dry_run)
        concept_count = create_concepts(session, SOURCE_DEFINITIONS, args.dry_run)
        mapping_count = add_mappings(session, SOURCE_DEFINITIONS, args.dry_run)
        score_count = recompute_scores(session, args.dry_run)

        if args.dry_run:
            session.rollback()
            logger.info("--- Dry-run summary ---")
        else:
            session.commit()
            logger.info("--- Committed ---")
        logger.info("  Semantic contexts set: %d", ctx_count)
        logger.info("  Concepts created:      %d", concept_count)
        logger.info("  Mappings added:        %d", mapping_count)
        logger.info("  Scores updated:        %d", score_count)
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


if __name__ == "__main__":
    main()
