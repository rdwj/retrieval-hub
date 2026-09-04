#!/usr/bin/env python3
"""Seed semantic_context entity aliases for graph sources.

Populates the SemanticContext.entities field with entity definitions
that include cross-domain aliases, enabling doc_section alias resolution
(e.g., querying for "Condition" matches SNOMED's "Disorder").

Usage:
    python scripts/seed_graph_entity_aliases.py [--db-url URL]
"""

from __future__ import annotations

import argparse
import json
import logging

import psycopg

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

DEFAULT_DB_URL = "postgresql://retrievalhub:retrievalhub@127.0.0.1:5434/retrievalhub"

ENTITY_ALIASES: dict[str, list[dict]] = {
    "fhir-hypertension": [
        {
            "name": "Patient",
            "entity_type": "clinical",
            "definition": "A patient demographic record with gender and birth date.",
            "aliases": [],
        },
        {
            "name": "Condition",
            "entity_type": "clinical",
            "definition": "A clinical condition or diagnosis (SNOMED-coded).",
            "aliases": ["Disorder", "Disease", "Diagnosis"],
        },
        {
            "name": "MedicationRequest",
            "entity_type": "clinical",
            "definition": "A prescribed medication with status and date.",
            "aliases": ["Medication", "Drug", "Compound", "Prescription"],
        },
        {
            "name": "Observation",
            "entity_type": "clinical",
            "definition": "A clinical observation (vitals, lab results).",
            "aliases": ["Vital", "Lab", "Measurement", "Finding"],
        },
        {
            "name": "Encounter",
            "entity_type": "clinical",
            "definition": "A clinical encounter with start and end dates.",
            "aliases": ["Visit"],
        },
        {
            "name": "Procedure",
            "entity_type": "clinical",
            "definition": "A clinical procedure performed on the patient.",
            "aliases": [],
        },
        {
            "name": "CarePlan",
            "entity_type": "clinical",
            "definition": "A care plan addressing one or more conditions.",
            "aliases": ["Care Plan", "Treatment Plan"],
        },
    ],
    "snomed-ct-hypertension": [
        {
            "name": "Disorder",
            "entity_type": "ontology",
            "definition": "A clinical disorder in the SNOMED-CT hierarchy.",
            "aliases": ["Condition", "Disease", "Diagnosis"],
        },
        {
            "name": "Finding",
            "entity_type": "ontology",
            "definition": "A clinical finding or observable state.",
            "aliases": ["Symptom", "Observation"],
        },
        {
            "name": "Body Structure",
            "entity_type": "ontology",
            "definition": "An anatomical body structure.",
            "aliases": ["Anatomy", "Body Part"],
        },
        {
            "name": "Observable Entity",
            "entity_type": "ontology",
            "definition": "A measurable or observable clinical entity.",
            "aliases": ["Measurement", "Vital"],
        },
        {
            "name": "Procedure",
            "entity_type": "ontology",
            "definition": "A clinical or surgical procedure.",
            "aliases": [],
        },
        {
            "name": "Substance",
            "entity_type": "ontology",
            "definition": "A chemical or biological substance.",
            "aliases": ["Drug", "Compound", "Medication"],
        },
        {
            "name": "Morphologic Abnormality",
            "entity_type": "ontology",
            "definition": "An abnormal morphological structure.",
            "aliases": [],
        },
    ],
    "hetionet-hypertension": [
        {
            "name": "Disease",
            "entity_type": "biomedical",
            "definition": "A disease in the Hetionet knowledge graph.",
            "aliases": ["Condition", "Disorder", "Diagnosis"],
        },
        {
            "name": "Compound",
            "entity_type": "biomedical",
            "definition": "A chemical compound (drug) with targets and relationships.",
            "aliases": ["Drug", "Medication", "MedicationRequest"],
        },
        {
            "name": "Gene",
            "entity_type": "biomedical",
            "definition": "A gene with disease associations and regulatory data.",
            "aliases": [],
        },
        {
            "name": "Anatomy",
            "entity_type": "biomedical",
            "definition": "An anatomical structure where genes are expressed.",
            "aliases": ["Body Structure", "Body Part"],
        },
        {
            "name": "Symptom",
            "entity_type": "biomedical",
            "definition": "A symptom associated with a disease.",
            "aliases": ["Finding", "Observation"],
        },
    ],
}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db-url", default=DEFAULT_DB_URL)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    with psycopg.connect(args.db_url) as conn:
        for slug, entities in ENTITY_ALIASES.items():
            cur = conn.execute(
                "SELECT semantic_context FROM source WHERE slug = %s", (slug,)
            )
            row = cur.fetchone()
            if not row:
                logger.warning("Source %s not found, skipping", slug)
                continue

            existing = row[0]
            if existing and existing != "null":
                sc = json.loads(existing) if isinstance(existing, str) else existing
            else:
                sc = {}

            sc["entities"] = entities
            new_val = json.dumps(sc)

            if args.dry_run:
                logger.info("[DRY RUN] %s: %d entities", slug, len(entities))
                continue

            conn.execute(
                "UPDATE source SET semantic_context = %s::json WHERE slug = %s",
                (new_val, slug),
            )
            logger.info("Updated %s: %d entities", slug, len(entities))

        if not args.dry_run:
            conn.commit()
            logger.info("Committed")


if __name__ == "__main__":
    main()
