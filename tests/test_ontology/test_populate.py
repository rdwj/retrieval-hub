"""Tests for the incremental ontology registry population logic."""

from __future__ import annotations

from retrieval_hub.models.ontology import OntologyMapping
from retrieval_hub.ontology import populate_ontology_for_source

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _count_mappings(session) -> int:
    return session.query(OntologyMapping).count()


def _get_mappings(session) -> list[tuple[str, str, str]]:
    """Return all (canonical_name, source_slug, local_name) sorted."""
    rows = session.query(OntologyMapping).order_by(
        OntologyMapping.canonical_name,
        OntologyMapping.source_slug,
    ).all()
    return [(r.canonical_name, r.source_slug, r.local_name) for r in rows]


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_new_source_no_existing_mappings(session):
    """Entities with no prior registry entries become new canonical names."""
    entities = [
        {"name": "Patient", "aliases": ["Subject"]},
        {"name": "Condition", "aliases": ["Disorder"]},
    ]

    inserted = populate_ontology_for_source("fhir", entities, session)

    assert inserted == 2
    assert _count_mappings(session) == 2
    mappings = _get_mappings(session)
    assert ("Condition", "fhir", "Condition") in mappings
    assert ("Patient", "fhir", "Patient") in mappings


def test_matches_existing_canonical_by_name(session):
    """A new source's entity name that matches an existing canonical reuses it."""
    session.add(OntologyMapping(
        canonical_name="Condition",
        source_slug="fhir",
        local_name="Condition",
    ))
    session.flush()

    entities = [{"name": "Condition", "aliases": []}]
    inserted = populate_ontology_for_source("snomed", entities, session)

    assert inserted == 1
    assert _count_mappings(session) == 2
    mappings = _get_mappings(session)
    assert ("Condition", "snomed", "Condition") in mappings


def test_matches_existing_canonical_by_alias(session):
    """A new entity's alias that matches an existing local_name joins that group."""
    session.add(OntologyMapping(
        canonical_name="Condition",
        source_slug="fhir",
        local_name="Condition",
    ))
    session.flush()

    entities = [{"name": "Disorder", "aliases": ["Condition", "Disease"]}]
    inserted = populate_ontology_for_source("snomed", entities, session)

    assert inserted == 1
    mappings = _get_mappings(session)
    assert ("Condition", "snomed", "Disorder") in mappings


def test_case_insensitive_matching(session):
    """Matching is case-insensitive for both names and aliases."""
    session.add(OntologyMapping(
        canonical_name="Condition",
        source_slug="fhir",
        local_name="Condition",
    ))
    session.flush()

    entities = [{"name": "CONDITION", "aliases": []}]
    inserted = populate_ontology_for_source("snomed", entities, session)

    assert inserted == 1
    mappings = _get_mappings(session)
    assert ("Condition", "snomed", "CONDITION") in mappings


def test_idempotent_on_duplicate(session):
    """Running twice with the same data does not duplicate rows."""
    entities = [{"name": "Patient", "aliases": ["Subject"]}]

    first = populate_ontology_for_source("fhir", entities, session)
    second = populate_ontology_for_source("fhir", entities, session)

    assert first == 1
    assert second == 0
    assert _count_mappings(session) == 1


def test_empty_entities_returns_zero(session):
    """An empty entity list returns 0 and does nothing."""
    assert populate_ontology_for_source("fhir", [], session) == 0
    assert _count_mappings(session) == 0


def test_entity_without_name_skipped(session):
    """Entities missing the 'name' key are silently skipped."""
    entities = [{"aliases": ["X"]}, {"name": "Valid"}]
    inserted = populate_ontology_for_source("src", entities, session)

    assert inserted == 1
    assert _count_mappings(session) == 1


def test_multiple_entities_one_matching(session):
    """Mixed bag: one entity matches existing, another is new."""
    session.add(OntologyMapping(
        canonical_name="Patient",
        source_slug="fhir",
        local_name="Patient",
    ))
    session.flush()

    entities = [
        {"name": "Subject", "aliases": ["Patient"]},
        {"name": "Medication"},
    ]
    inserted = populate_ontology_for_source("snomed", entities, session)

    assert inserted == 2
    mappings = _get_mappings(session)
    assert ("Patient", "snomed", "Subject") in mappings
    assert ("Medication", "snomed", "Medication") in mappings


def test_new_entity_added_to_lookup_for_subsequent(session):
    """A new canonical name is visible to later entities in the same batch."""
    entities = [
        {"name": "Compound"},
        {"name": "Drug", "aliases": ["Compound"]},
    ]
    inserted = populate_ontology_for_source("hetionet", entities, session)

    assert inserted == 2
    mappings = _get_mappings(session)
    assert ("Compound", "hetionet", "Compound") in mappings
    assert ("Compound", "hetionet", "Drug") in mappings
