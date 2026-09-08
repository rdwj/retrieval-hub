"""Tests for the OntologyConcept model and hierarchy features."""

from __future__ import annotations

from retrieval_hub.models.enums import SourceFamily
from retrieval_hub.models.ontology import OntologyMapping
from retrieval_hub.models.ontology_concept import OntologyConcept
from retrieval_hub.retrieval.api import (
    _expand_concepts_via_hierarchy,
    expand_doc_section_via_registry,
)


class TestOntologyConcept:
    """Basic model tests for ontology_concept."""

    def test_create_concept(self, session):
        session.add(OntologyConcept(name="Condition"))
        session.flush()

        row = session.query(OntologyConcept).filter_by(name="Condition").one()
        assert row.name == "Condition"
        assert row.parent_name is None
        assert row.created_at is not None

    def test_create_concept_with_parent(self, session):
        session.add(OntologyConcept(name="Condition"))
        session.flush()
        session.add(OntologyConcept(name="Hypertension", parent_name="Condition"))
        session.flush()

        child = session.query(OntologyConcept).filter_by(name="Hypertension").one()
        assert child.parent_name == "Condition"

    def test_multiple_children(self, session):
        session.add(OntologyConcept(name="Condition"))
        session.flush()
        session.add_all([
            OntologyConcept(name="Hypertension", parent_name="Condition"),
            OntologyConcept(name="PTSD", parent_name="Condition"),
            OntologyConcept(name="MDD", parent_name="Condition"),
        ])
        session.flush()

        children = (
            session.query(OntologyConcept)
            .filter(OntologyConcept.parent_name == "Condition")
            .all()
        )
        assert len(children) == 3
        names = {c.name for c in children}
        assert names == {"Hypertension", "PTSD", "MDD"}


class TestExpandConceptsViaHierarchy:
    """Tests for _expand_concepts_via_hierarchy."""

    def test_no_hierarchy(self, session):
        session.add(OntologyConcept(name="Condition"))
        session.flush()

        result = _expand_concepts_via_hierarchy(session, {"Condition"})
        assert result == {"Condition"}

    def test_single_level(self, session):
        session.add(OntologyConcept(name="Condition"))
        session.flush()
        session.add_all([
            OntologyConcept(name="Hypertension", parent_name="Condition"),
            OntologyConcept(name="PTSD", parent_name="Condition"),
        ])
        session.flush()

        result = _expand_concepts_via_hierarchy(session, {"Condition"})
        assert result == {"Condition", "Hypertension", "PTSD"}

    def test_multi_level(self, session):
        session.add(OntologyConcept(name="Condition"))
        session.flush()
        session.add(OntologyConcept(name="Substance Use Disorder", parent_name="Condition"))
        session.flush()
        session.add(OntologyConcept(
            name="Alcohol Use Disorder", parent_name="Substance Use Disorder",
        ))
        session.flush()

        result = _expand_concepts_via_hierarchy(session, {"Condition"})
        assert result == {"Condition", "Substance Use Disorder", "Alcohol Use Disorder"}

    def test_depth_limit(self, session):
        """Hierarchy traversal respects the max_depth parameter."""
        session.add(OntologyConcept(name="L0"))
        session.flush()
        for i in range(1, 8):
            session.add(OntologyConcept(name=f"L{i}", parent_name=f"L{i-1}"))
            session.flush()

        result = _expand_concepts_via_hierarchy(session, {"L0"}, max_depth=3)
        assert "L0" in result
        assert "L1" in result
        assert "L2" in result
        assert "L3" in result
        assert "L4" not in result

    def test_empty_input(self, session):
        result = _expand_concepts_via_hierarchy(session, set())
        assert result == set()

    def test_leaf_concept(self, session):
        """A leaf concept with no children returns just itself."""
        session.add(OntologyConcept(name="Condition"))
        session.flush()
        session.add(OntologyConcept(name="Hypertension", parent_name="Condition"))
        session.flush()

        result = _expand_concepts_via_hierarchy(session, {"Hypertension"})
        assert result == {"Hypertension"}

    def test_multiple_roots(self, session):
        """Expanding multiple root concepts collects all descendants."""
        session.add_all([
            OntologyConcept(name="Condition"),
            OntologyConcept(name="Compound"),
        ])
        session.flush()
        session.add_all([
            OntologyConcept(name="Hypertension", parent_name="Condition"),
            OntologyConcept(name="Metformin", parent_name="Compound"),
        ])
        session.flush()

        result = _expand_concepts_via_hierarchy(
            session, {"Condition", "Compound"},
        )
        assert result == {"Condition", "Hypertension", "Compound", "Metformin"}


class TestHierarchyExpansionInRetrievalApi:
    """Integration tests for hierarchy-aware doc_section expansion."""

    def _seed_hierarchy(self, session):
        """Seed a small hierarchy + mappings for testing."""
        session.add_all([
            OntologyConcept(name="Condition"),
            OntologyConcept(name="Compound"),
            OntologyConcept(name="Finding"),
        ])
        session.flush()
        session.add_all([
            OntologyConcept(name="Hypertension", parent_name="Condition"),
            OntologyConcept(name="PTSD", parent_name="Condition"),
            OntologyConcept(name="Metformin", parent_name="Compound"),
        ])
        session.flush()

        session.add_all([
            OntologyMapping(
                canonical_name="Condition", source_slug="fhir",
                local_name="Condition",
            ),
            OntologyMapping(
                canonical_name="Hypertension", source_slug="fhir",
                local_name="Hypertension",
            ),
            OntologyMapping(
                canonical_name="PTSD", source_slug="fhir",
                local_name="PTSD",
            ),
            OntologyMapping(
                canonical_name="Condition", source_slug="snomed",
                local_name="Disorder",
            ),
            OntologyMapping(
                canonical_name="Hypertension", source_slug="snomed",
                local_name="Essential hypertension",
            ),
            OntologyMapping(
                canonical_name="Compound", source_slug="hetionet",
                local_name="Compound",
            ),
            OntologyMapping(
                canonical_name="Metformin", source_slug="hetionet",
                local_name="Metformin",
            ),
            OntologyMapping(
                canonical_name="Finding", source_slug="fhir",
                local_name="Observation",
            ),
        ])
        session.flush()

    def test_hierarchy_expansion_parent_to_children(self, session):
        """Searching for 'Condition' expands to include 'Hypertension' and 'PTSD'."""
        self._seed_hierarchy(session)

        result = expand_doc_section_via_registry(
            session, "fhir", ["Condition"],
            source_family=SourceFamily.GRAPH,
        )
        result_set = set(result.doc_section)

        assert "Condition" in result_set
        assert "Hypertension" in result_set
        assert "PTSD" in result_set

    def test_hierarchy_expansion_cross_source(self, session):
        """Searching snomed for 'Condition' expands to include snomed's local names for children."""
        self._seed_hierarchy(session)

        result = expand_doc_section_via_registry(
            session, "snomed", ["Condition"],
            source_family=SourceFamily.GRAPH,
        )
        result_set = set(result.doc_section)

        assert "Disorder" in result_set
        assert "Essential hypertension" in result_set
        assert "Condition" in result_set

    def test_leaf_concept_no_extra_expansion(self, session):
        """Searching for a leaf concept does not add unrelated concepts."""
        self._seed_hierarchy(session)

        result = expand_doc_section_via_registry(
            session, "fhir", ["Hypertension"],
            source_family=SourceFamily.GRAPH,
        )
        result_set = set(result.doc_section)

        assert "Hypertension" in result_set
        assert "PTSD" not in result_set

    def test_flat_expansion_still_works(self, session):
        """Flat cross-source expansion (no hierarchy) continues to work."""
        self._seed_hierarchy(session)

        result = expand_doc_section_via_registry(
            session, "fhir", ["Disorder"],
            source_family=SourceFamily.GRAPH,
        )
        result_set = set(result.doc_section)

        assert "Disorder" in result_set
        assert "Condition" in result_set

    def test_no_hierarchy_data(self, session):
        """When ontology_concept has no parent edges, behaves like flat expansion."""
        session.add_all([
            OntologyConcept(name="Condition"),
            OntologyConcept(name="Hypertension"),
        ])
        session.flush()
        session.add_all([
            OntologyMapping(
                canonical_name="Condition", source_slug="fhir",
                local_name="Condition",
            ),
            OntologyMapping(
                canonical_name="Hypertension", source_slug="fhir",
                local_name="Hypertension",
            ),
        ])
        session.flush()

        result = expand_doc_section_via_registry(
            session, "fhir", ["Condition"],
            source_family=SourceFamily.GRAPH,
        )
        result_set = set(result.doc_section)

        assert "Condition" in result_set
        # Without hierarchy, Hypertension should NOT appear
        assert "Hypertension" not in result_set

    def test_none_and_empty_passthrough(self, session):
        """None and empty list still pass through unchanged."""
        self._seed_hierarchy(session)

        assert expand_doc_section_via_registry(session, "fhir", None).doc_section is None
        assert expand_doc_section_via_registry(session, "fhir", []).doc_section == []


class TestFamilyAwareHierarchyExpansion:
    """Tests that hierarchy expansion routes by source family."""

    def _seed_hierarchy(self, session):
        """Seed a small hierarchy + mappings for testing."""
        session.add_all([
            OntologyConcept(name="Condition"),
            OntologyConcept(name="Compound"),
            OntologyConcept(name="Finding"),
        ])
        session.flush()
        session.add_all([
            OntologyConcept(name="Hypertension", parent_name="Condition"),
            OntologyConcept(name="PTSD", parent_name="Condition"),
            OntologyConcept(name="Metformin", parent_name="Compound"),
        ])
        session.flush()

        session.add_all([
            OntologyMapping(
                canonical_name="Condition", source_slug="va-cpg",
                local_name="Condition",
            ),
            OntologyMapping(
                canonical_name="Hypertension", source_slug="va-cpg",
                local_name="Hypertension",
            ),
            OntologyMapping(
                canonical_name="PTSD", source_slug="va-cpg",
                local_name="PTSD",
            ),
            OntologyMapping(
                canonical_name="Condition", source_slug="hetionet",
                local_name="Disease",
            ),
            OntologyMapping(
                canonical_name="Hypertension", source_slug="hetionet",
                local_name="Hypertension",
            ),
            OntologyMapping(
                canonical_name="PTSD", source_slug="hetionet",
                local_name="PTSD",
            ),
        ])
        session.flush()

    def test_graph_source_hierarchy_in_doc_section(self, session):
        """For graph sources, hierarchy children go into doc_section."""
        self._seed_hierarchy(session)

        result = expand_doc_section_via_registry(
            session, "hetionet", ["Condition"],
            source_family=SourceFamily.GRAPH,
        )

        assert "Hypertension" in result.doc_section
        assert "PTSD" in result.doc_section
        assert "Disease" in result.doc_section
        assert result.query_terms == []

    def test_document_source_hierarchy_in_query_terms(self, session):
        """For document sources, hierarchy children go into query_terms."""
        self._seed_hierarchy(session)

        result = expand_doc_section_via_registry(
            session, "va-cpg", ["Condition"],
            source_family=SourceFamily.CLINICAL_DOCUMENT,
        )

        # Flat expansion: Condition stays in doc_section
        assert "Condition" in result.doc_section
        # Hierarchy children should NOT be in doc_section
        assert "Hypertension" not in result.doc_section
        assert "PTSD" not in result.doc_section
        # Hierarchy children should be in query_terms
        assert "Hypertension" in result.query_terms
        assert "PTSD" in result.query_terms

    def test_flat_expansion_same_for_all_families(self, session):
        """Flat (alias) expansion works the same regardless of family."""
        self._seed_hierarchy(session)

        # Add cross-source mapping
        session.add(OntologyMapping(
            canonical_name="Condition", source_slug="snomed",
            local_name="Disorder",
        ))
        session.flush()

        graph_result = expand_doc_section_via_registry(
            session, "hetionet", ["Disorder"],
            source_family=SourceFamily.GRAPH,
        )
        doc_result = expand_doc_section_via_registry(
            session, "hetionet", ["Disorder"],
            source_family=SourceFamily.CLINICAL_DOCUMENT,
        )

        # Flat expansion (alias resolution) should work the same
        assert "Disease" in graph_result.doc_section
        assert "Disease" in doc_result.doc_section
        assert "Disorder" in graph_result.doc_section
        assert "Disorder" in doc_result.doc_section

    def test_technical_document_family(self, session):
        """TECHNICAL_DOCUMENT family also routes hierarchy to query_terms."""
        self._seed_hierarchy(session)

        result = expand_doc_section_via_registry(
            session, "va-cpg", ["Condition"],
            source_family=SourceFamily.TECHNICAL_DOCUMENT,
        )

        assert "Condition" in result.doc_section
        assert "Hypertension" not in result.doc_section
        assert "Hypertension" in result.query_terms
