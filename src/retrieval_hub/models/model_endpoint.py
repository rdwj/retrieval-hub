"""Model endpoint registry ORM model.

Tracks embedding (and future reranking) model serving endpoints as shared
cluster infrastructure. Each row maps a model name to the URL where it is
served, along with a health status updated by a periodic probe.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import DateTime, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from retrieval_hub.db.base import Base


def _new_uuid() -> str:
    return str(uuid.uuid4())


def _utcnow() -> datetime:
    return datetime.now(UTC)


class ModelEndpoint(Base):
    """A registered model serving endpoint."""

    __tablename__ = "model_endpoint"
    __table_args__ = (
        UniqueConstraint("model_name", name="uq_model_endpoint_model_name"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=_new_uuid)
    model_name: Mapped[str] = mapped_column(String(256), nullable=False)
    endpoint_url: Mapped[str] = mapped_column(String(512), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="unknown")
    last_probed: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    registered_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow, onupdate=_utcnow
    )
