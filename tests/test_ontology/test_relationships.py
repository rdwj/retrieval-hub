"""Tests for the OntologyRelationship model."""

from __future__ import annotations

import pytest
from sqlalchemy import or_
from sqlalchemy.exc import IntegrityError

from retrieval_hub.models import OntologyRelationship


class TestOntologyRelationship:
    """Basic model tests for ontology_relationship."""

    def test_create_canonical_relationship(self, session):
        rel = OntologyRelationship(
            source_concept="Drug",
            relationship="treats",
            target_concept="Disease",
        )
        session.add(rel)
        session.flush()

        row = (
            session.query(OntologyRelationship)
            .filter_by(source_concept="Drug")
            .one()
        )
        assert row.id is not None
        assert row.source_concept == "Drug"
        assert row.relationship == "treats"
        assert row.target_concept == "Disease"
        assert row.source_slug is None
        assert row.created_at is not None

    def test_create_source_specific_relationship(self, session):
        rel = OntologyRelationship(
            source_concept="Drug",
            relationship="treats",
            target_concept="Disease",
            source_slug="fhir",
        )
        session.add(rel)
        session.flush()

        row = (
            session.query(OntologyRelationship)
            .filter_by(source_slug="fhir")
            .one()
        )
        assert row.source_slug == "fhir"

    def test_unique_constraint_prevents_duplicates(self, session):
        kwargs = dict(
            source_concept="Drug",
            relationship="treats",
            target_concept="Disease",
            source_slug="fhir",
        )
        session.add(OntologyRelationship(**kwargs))
        session.flush()

        session.add(OntologyRelationship(**kwargs))
        with pytest.raises(IntegrityError):
            session.flush()
        session.rollback()

    def test_same_relationship_different_source_slug_allowed(
        self, session,
    ):
        session.add(OntologyRelationship(
            source_concept="Drug",
            relationship="treats",
            target_concept="Disease",
            source_slug=None,
        ))
        session.add(OntologyRelationship(
            source_concept="Drug",
            relationship="treats",
            target_concept="Disease",
            source_slug="fhir",
        ))
        session.flush()

        rows = (
            session.query(OntologyRelationship)
            .filter_by(
                source_concept="Drug",
                relationship="treats",
                target_concept="Disease",
            )
            .all()
        )
        slugs = {r.source_slug for r in rows}
        assert slugs == {None, "fhir"}

    def test_multiple_relationships_between_same_concepts(
        self, session,
    ):
        session.add_all([
            OntologyRelationship(
                source_concept="Drug",
                relationship="treats",
                target_concept="Disease",
            ),
            OntologyRelationship(
                source_concept="Drug",
                relationship="palliates",
                target_concept="Disease",
            ),
        ])
        session.flush()

        rows = (
            session.query(OntologyRelationship)
            .filter_by(
                source_concept="Drug",
                target_concept="Disease",
            )
            .all()
        )
        verbs = {r.relationship for r in rows}
        assert verbs == {"treats", "palliates"}

    def test_query_by_source_concept(self, session):
        session.add_all([
            OntologyRelationship(
                source_concept="Drug",
                relationship="treats",
                target_concept="Disease",
            ),
            OntologyRelationship(
                source_concept="Drug",
                relationship="interacts_with",
                target_concept="Gene",
            ),
            OntologyRelationship(
                source_concept="Gene",
                relationship="causes",
                target_concept="Disease",
            ),
        ])
        session.flush()

        rows = (
            session.query(OntologyRelationship)
            .filter(OntologyRelationship.source_concept == "Drug")
            .all()
        )
        assert len(rows) == 2
        targets = {r.target_concept for r in rows}
        assert targets == {"Disease", "Gene"}

    def test_query_by_target_concept(self, session):
        session.add_all([
            OntologyRelationship(
                source_concept="Drug",
                relationship="treats",
                target_concept="Disease",
            ),
            OntologyRelationship(
                source_concept="Gene",
                relationship="causes",
                target_concept="Disease",
            ),
            OntologyRelationship(
                source_concept="Drug",
                relationship="binds",
                target_concept="Gene",
            ),
        ])
        session.flush()

        rows = (
            session.query(OntologyRelationship)
            .filter(
                OntologyRelationship.target_concept == "Disease",
            )
            .all()
        )
        assert len(rows) == 2
        sources = {r.source_concept for r in rows}
        assert sources == {"Drug", "Gene"}

    def test_query_relationships_for_concept_both_directions(
        self, session,
    ):
        session.add_all([
            OntologyRelationship(
                source_concept="Disease",
                relationship="treated_by",
                target_concept="Drug",
            ),
            OntologyRelationship(
                source_concept="Gene",
                relationship="causes",
                target_concept="Disease",
            ),
            OntologyRelationship(
                source_concept="Drug",
                relationship="binds",
                target_concept="Gene",
            ),
        ])
        session.flush()

        rows = (
            session.query(OntologyRelationship)
            .filter(or_(
                OntologyRelationship.source_concept == "Disease",
                OntologyRelationship.target_concept == "Disease",
            ))
            .all()
        )
        assert len(rows) == 2
        verbs = {r.relationship for r in rows}
        assert verbs == {"treated_by", "causes"}
