"""Per-mapping query metrics for ontology monitoring."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import DateTime, Float, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from retrieval_hub.db.base import Base


def _utcnow() -> datetime:
    return datetime.now(UTC)


class OntologyQueryMetric(Base):
    """Records per-mapping retrieval metrics at query time."""

    __tablename__ = "ontology_query_metric"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    mapping_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    source_slug: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    canonical_name: Mapped[str] = mapped_column(String(256), nullable=False, index=True)
    hit_count: Mapped[int] = mapped_column(Integer, nullable=False)
    top_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    query_timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow, index=True
    )
