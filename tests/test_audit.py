"""Tests for the audit writer utility."""

from __future__ import annotations

from retrieval_hub.audit import write_audit_record
from retrieval_hub.models.audit import AuditRecord
from retrieval_hub.models.enums import SourceStatus
from retrieval_hub.models.identity import Identity
from tests.conftest import make_source


def test_write_audit_record_string_actor(session):
    src = make_source(session)
    record = write_audit_record(
        session,
        action="source.created",
        source_id=src.id,
        actor="script:test",
        details={"slug": src.slug},
    )
    session.flush()

    assert record.identity_sub == "script:test"
    assert record.identity_kind == "service"
    assert record.action == "source.created"
    assert record.source_id == src.id
    assert record.details["slug"] == src.slug


def test_write_audit_record_identity_actor(session):
    src = make_source(session)
    identity = Identity(
        sub="user:alice",
        kind="user",
        request_id="req-123",
    )
    record = write_audit_record(
        session,
        action="source.updated",
        source_id=src.id,
        actor=identity,
        details={"slug": src.slug},
    )
    session.flush()

    assert record.identity_sub == "user:alice"
    assert record.identity_kind == "user"
    assert record.request_id == "req-123"


def test_write_audit_record_no_actor(session):
    record = write_audit_record(
        session,
        action="source.deleted",
    )
    session.flush()

    assert record.identity_sub == "unknown"
    assert record.identity_kind == "service"


def test_transition_to_writes_audit(session):
    src = make_source(session, status=SourceStatus.DRAFT)
    src.transition_to(
        SourceStatus.CURATED,
        session=session,
        actor="script:test",
    )
    session.flush()

    records = (
        session.query(AuditRecord)
        .filter(
            AuditRecord.source_id == src.id,
            AuditRecord.action == "source.status_changed",
        )
        .all()
    )

    assert len(records) == 1
    assert records[0].details["old_status"] == "draft"
    assert records[0].details["new_status"] == "curated"


def test_transition_to_noop_same_status(session):
    src = make_source(session, status=SourceStatus.DRAFT)
    src.transition_to(
        SourceStatus.DRAFT,
        session=session,
        actor="script:test",
    )
    session.flush()

    records = (
        session.query(AuditRecord)
        .filter(AuditRecord.source_id == src.id)
        .all()
    )
    assert len(records) == 0


def test_register_creates_audit_records(session):
    from retrieval_hub.ingestion.register import register_document_source

    result = register_document_source(
        session,
        slug="test-audit-src",
        name="Test Audit Source",
        description_short="Short desc",
        description_long="Long desc",
        owner_team="test-team",
        owner_contacts=["test@example.com"],
        recipe_content={"parser": {"kind": "docling"}, "chunker": {"size": 512}},
        physical_index_location="idx_test_audit_v1",
        document_count=10,
        chunk_count=100,
        triggered_by="script:test",
    )

    records = (
        session.query(AuditRecord)
        .filter(AuditRecord.source_id == result.source_id)
        .all()
    )
    assert len(records) == 1
    assert records[0].action == "source.created"
    assert records[0].identity_sub == "script:test"
