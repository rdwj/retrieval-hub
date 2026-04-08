"""ORM model for ingestion runs.

An ingestion run materializes a physical index from a recipe version. The
catalog records the run's lifecycle and a result manifest; the actual stage
machinery (fetch / parse / normalize / chunk / embed / write / register)
lives in the (future) ingestion subsystem and is not part of this slice.

See ``docs/ingestion.md``.
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
from retrieval_hub.models.enums import (
    IngestionStatus,
    RefreshMode,
    TriggeredByKind,
)


def _new_uuid() -> str:
    return str(uuid.uuid4())


def _utcnow() -> datetime:
    return datetime.now(UTC)


class IngestionRun(Base):
    """A single ingestion-pipeline execution against a source + recipe version."""

    __tablename__ = "ingestion_run"
    __table_args__ = (
        Index("ix_ingestion_run_source_id", "source_id"),
        Index("ix_ingestion_run_status", "status"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=_new_uuid)
    source_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("source.id", name="fk_ingestion_run_source_id_source", ondelete="CASCADE"),
        nullable=False,
    )
    recipe_version_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey(
            "recipe_version.id",
            name="fk_ingestion_run_recipe_version_id_recipe_version",
        ),
        nullable=False,
    )
    refresh_mode: Mapped[RefreshMode] = mapped_column(String(32), nullable=False)
    status: Mapped[IngestionStatus] = mapped_column(
        String(32), nullable=False, default=IngestionStatus.PENDING
    )
    stages_completed: Mapped[list[str] | None] = mapped_column(JSONType, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    triggered_by: Mapped[str | None] = mapped_column(String(128), nullable=True)
    triggered_by_kind: Mapped[TriggeredByKind | None] = mapped_column(String(32), nullable=True)
    result_manifest: Mapped[dict[str, Any] | None] = mapped_column(JSONType, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )
