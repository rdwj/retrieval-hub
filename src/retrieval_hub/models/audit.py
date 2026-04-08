"""ORM model for the catalog audit log.

Every state transition, agent write, recipe bump, and admin action produces an
audit record. The table is append-only at the application level (the
``AuditWriter`` service in a future step will be the only writer; for this
slice we just expose the model).

See ``docs/catalog.md`` "Agent writes" and "Source lifecycle".
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Index,
    String,
)
from sqlalchemy.orm import Mapped, mapped_column

from retrieval_hub.db.base import Base
from retrieval_hub.db.types import JSONType


def _new_uuid() -> str:
    return str(uuid.uuid4())


def _utcnow() -> datetime:
    return datetime.now(UTC)


class AuditRecord(Base):
    """An immutable record of one catalog state transition or agent write."""

    __tablename__ = "audit_record"
    __table_args__ = (
        Index("ix_audit_record_occurred_at", "occurred_at"),
        Index("ix_audit_record_source_id", "source_id"),
        Index("ix_audit_record_action", "action"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=_new_uuid)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )
    identity_sub: Mapped[str] = mapped_column(String(256), nullable=False)
    identity_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    action: Mapped[str] = mapped_column(String(128), nullable=False)
    source_id: Mapped[str | None] = mapped_column(
        String(64),
        ForeignKey(
            "source.id",
            name="fk_audit_record_source_id_source",
            ondelete="SET NULL",
        ),
        nullable=True,
    )
    details: Mapped[dict[str, Any] | None] = mapped_column(JSONType, nullable=True)
    request_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
