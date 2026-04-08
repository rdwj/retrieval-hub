"""Tests for the ``AuditRecord`` model."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from retrieval_hub.models import AuditRecord
from tests.conftest import make_source


def test_audit_record_insert_and_query_by_action(session: Session) -> None:
    """Audit records persist and are queryable by ``action``."""
    src = make_source(session, slug="auditable-src")
    session.commit()

    rec = AuditRecord(
        id=str(uuid.uuid4()),
        occurred_at=datetime.now(UTC),
        identity_sub="user:alice",
        identity_kind="user",
        action="source.publish",
        source_id=src.id,
        details={"reason": "promote v1"},
        request_id="req_test_001",
    )
    session.add(rec)
    session.commit()

    rows = session.execute(
        select(AuditRecord).where(AuditRecord.action == "source.publish")
    ).scalars().all()
    assert len(rows) == 1
    assert rows[0].identity_sub == "user:alice"
    assert rows[0].source_id == src.id
    assert rows[0].details == {"reason": "promote v1"}


def test_audit_record_without_source(session: Session) -> None:
    """Audit records can be unattached to a source (e.g. system events)."""
    rec = AuditRecord(
        id=str(uuid.uuid4()),
        occurred_at=datetime.now(UTC),
        identity_sub="service:scheduler",
        identity_kind="service",
        action="system.startup",
        source_id=None,
        details=None,
    )
    session.add(rec)
    session.commit()

    fetched = session.get(AuditRecord, rec.id)
    assert fetched is not None
    assert fetched.source_id is None
