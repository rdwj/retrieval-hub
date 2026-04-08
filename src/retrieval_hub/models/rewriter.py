"""Rewriter-related ORM models.

The full per-source rewriter metadata (vocabulary mappings, sample queries,
domain notes, schema hints, runtime resolution settings) lives as the
``Source.rewriter_metadata`` JSON column. That keeps the strongly-coupled,
hot-path metadata next to the source row.

This module exists for the **rare** case where a source uses a per-source
override prompt registered in MLflow's prompt registry (or a local fallback).
``RewritePromptRef`` is the small lookup table that records that override.

See ``docs/catalog.md`` "Rewriter metadata" and ``docs/integrations/mlflow.md``.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, Index, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from retrieval_hub.db.base import Base

if TYPE_CHECKING:
    from retrieval_hub.models.source import Source


def _new_uuid() -> str:
    return str(uuid.uuid4())


def _utcnow() -> datetime:
    return datetime.now(UTC)


class RewritePromptRef(Base):
    """A reference to an MLflow-registered (or fallback-local) override prompt."""

    __tablename__ = "rewrite_prompt_ref"
    __table_args__ = (
        Index("ix_rewrite_prompt_ref_source_id", "source_id"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=_new_uuid)
    source_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey(
            "source.id",
            name="fk_rewrite_prompt_ref_source_id_source",
            ondelete="CASCADE",
        ),
        nullable=False,
    )
    prompt_slug: Mapped[str] = mapped_column(String(256), nullable=False)
    active_version: Mapped[int] = mapped_column(nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )

    source: Mapped[Source] = relationship("Source")
