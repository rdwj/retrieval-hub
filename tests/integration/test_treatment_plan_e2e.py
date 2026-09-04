"""End-to-end treatment plan workflow via the retrieval API.

Exercises the 7-query forcing-function from the agent integration guide:
find a patient, gather clinical data, fetch guidelines, enrich with
terminology, check drug context. Each step calls the retrieval API
against live databases.

Requires port-forwards to catalog DB, vectors DB, and embedding endpoint.
Skipped automatically when databases are unreachable.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest
from sqlalchemy.orm import Session

from retrieval_hub.retrieval.api import query as retrieval_query

PATIENT_NAME = "Charlena Brakus"
PATIENT_UUID = "596bb739-0d6a-038d-5160-7f870f9cea7a"


def _query(
    session: Session,
    source: str,
    query_text: str,
    vectors_db_url: str,
    embedding_endpoint: str,
    *,
    doc_section: list[str] | None = None,
    scope_entity_id: str | None = None,
):
    """Call retrieval_query with the embedding endpoint override."""
    with patch(
        "retrieval_hub.retrieval.api._resolve_embedding_endpoint",
        return_value=embedding_endpoint,
    ):
        return retrieval_query(
            source_slug=source,
            query_text=query_text,
            session=session,
            top_k=5,
            vectors_db_url=vectors_db_url,
            doc_section=doc_section,
            scope_entity_id=scope_entity_id,
        )


# -----------------------------------------------------------------------
# Individual query tests
# -----------------------------------------------------------------------

QUERIES = [
    pytest.param(
        "fhir-hypertension", PATIENT_NAME,
        {"doc_section": ["Patient"]},
        {"min_hits": 1, "text_contains": "Charlena"},
        id="find-patient",
    ),
    pytest.param(
        "fhir-hypertension", "conditions diagnoses",
        {"doc_section": ["Condition"], "scope_entity_id": PATIENT_UUID},
        {"min_hits": 1, "section": "Condition"},
        id="patient-conditions",
    ),
    pytest.param(
        "fhir-hypertension", "medications",
        {"doc_section": ["MedicationRequest"], "scope_entity_id": PATIENT_UUID},
        {"min_hits": 1, "section": "MedicationRequest"},
        id="patient-medications",
    ),
    pytest.param(
        "fhir-hypertension", "blood pressure vitals",
        {"doc_section": ["Observation"], "scope_entity_id": PATIENT_UUID},
        {"min_hits": 1},
        id="patient-vitals",
    ),
    pytest.param(
        "va-cpg-clinical-guidelines",
        "hypertension treatment first-line medication",
        {},
        {"min_hits": 1},
        id="treatment-guidelines",
    ),
    pytest.param(
        "snomed-ct-hypertension",
        "essential hypertension classification",
        {},
        {"min_hits": 1},
        id="snomed-terminology",
    ),
    pytest.param(
        "hetionet-hypertension",
        "Hydrochlorothiazide targets interactions",
        {},
        {"min_hits": 1},
        id="drug-context",
    ),
]


@pytest.mark.integration
@pytest.mark.parametrize("source,query_text,kwargs,assertions", QUERIES)
def test_retrieve_query(
    catalog_session, vectors_db_url, embedding_endpoint,
    source, query_text, kwargs, assertions,
):
    """Each query in the treatment plan workflow returns useful results."""
    results = _query(
        catalog_session, source, query_text,
        vectors_db_url, embedding_endpoint, **kwargs,
    )

    assert len(results) >= assertions["min_hits"], (
        f"Expected >= {assertions['min_hits']} hits, got {len(results)}. "
        f"Source: {source}, query: {query_text!r}"
    )

    if "text_contains" in assertions:
        combined = " ".join(r.text for r in results)
        assert assertions["text_contains"].lower() in combined.lower(), (
            f"Expected '{assertions['text_contains']}' in hit text"
        )

    if "section" in assertions:
        sections = {r.doc_section for r in results}
        assert assertions["section"] in sections, (
            f"Expected section={assertions['section']}, got {sections}"
        )


# -----------------------------------------------------------------------
# Full workflow test — validates cross-step data flow
# -----------------------------------------------------------------------


@pytest.mark.integration
def test_full_treatment_plan_workflow(
    catalog_session, vectors_db_url, embedding_endpoint,
):
    """Run the complete 7-step workflow, using step 1's output in steps 2-4."""
    # Step 1: Find patient
    results = _query(
        catalog_session, "fhir-hypertension", PATIENT_NAME,
        vectors_db_url, embedding_endpoint,
        doc_section=["Patient"],
    )
    assert len(results) >= 1, "No Patient hits found"
    patient_uuid = results[0].doc_title
    assert patient_uuid, "Patient hit missing doc_title (UUID)"

    # Steps 2-4: Scoped clinical data using the discovered UUID
    for section, q in [
        ("Condition", "conditions diagnoses"),
        ("MedicationRequest", "medications"),
        ("Observation", "blood pressure vitals"),
    ]:
        results = _query(
            catalog_session, "fhir-hypertension", q,
            vectors_db_url, embedding_endpoint,
            doc_section=[section], scope_entity_id=patient_uuid,
        )
        assert len(results) >= 1, (
            f"No {section} hits for patient {patient_uuid}"
        )

    # Steps 5-7: Cross-source enrichment
    for source, q in [
        ("va-cpg-clinical-guidelines",
         "hypertension treatment first-line medication"),
        ("snomed-ct-hypertension",
         "essential hypertension classification"),
        ("hetionet-hypertension",
         "Hydrochlorothiazide targets interactions"),
    ]:
        results = _query(
            catalog_session, source, q,
            vectors_db_url, embedding_endpoint,
        )
        assert len(results) >= 1, (
            f"No hits from {source} for query '{q}'"
        )
