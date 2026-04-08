"""ORM models for the evaluation subsystem.

Eval *suites* are catalog objects (definitions of metrics, applicable family,
dataset references). Eval *runs* are the individual executions against a
specific physical index. Eval *results* are the per-case projections we keep
locally for display; the full history of record may live in MLflow when wired.

See ``docs/catalog.md`` "Ownership boundary with platform capabilities" and
``docs/integrations/mlflow.md`` for the lineage pointer fields.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from retrieval_hub.db.base import Base
from retrieval_hub.db.types import JSONType
from retrieval_hub.models.enums import (
    EvalRunStatus,
    EvalSuiteFamily,
    ExecutionBackend,
    MlflowSyncState,
    TriggeredByKind,
)


def _new_uuid() -> str:
    return str(uuid.uuid4())


def _utcnow() -> datetime:
    return datetime.now(UTC)


class EvalSuite(Base):
    """A reusable definition of *what* to evaluate (metrics, dataset, family)."""

    __tablename__ = "eval_suite"
    __table_args__ = (
        UniqueConstraint("slug", "version_number", name="uq_eval_suite_slug_version_number"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=_new_uuid)
    slug: Mapped[str] = mapped_column(String(128), nullable=False)
    name: Mapped[str] = mapped_column(String(256), nullable=False)
    applies_to_family: Mapped[EvalSuiteFamily] = mapped_column(String(32), nullable=False)
    version_number: Mapped[int] = mapped_column(nullable=False, default=1)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    metric_set: Mapped[dict[str, Any]] = mapped_column(JSONType, nullable=False)

    mlflow_experiment_name: Mapped[str | None] = mapped_column(String(256), nullable=True)
    mlflow_dataset_name: Mapped[str | None] = mapped_column(String(256), nullable=True)
    test_cases_storage_uri: Mapped[str | None] = mapped_column(String(512), nullable=True)
    case_schema_id: Mapped[str | None] = mapped_column(String(128), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )
    created_by: Mapped[str | None] = mapped_column(String(128), nullable=True)

    runs: Mapped[list[EvalRun]] = relationship("EvalRun", back_populates="eval_suite")


class EvalRun(Base):
    """A single execution of an eval suite against a physical index."""

    __tablename__ = "eval_run"
    __table_args__ = (
        Index("ix_eval_run_source_id", "source_id"),
        Index("ix_eval_run_physical_index_id", "physical_index_id"),
        Index("ix_eval_run_eval_suite_id", "eval_suite_id"),
        Index("ix_eval_run_status", "status"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=_new_uuid)
    source_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("source.id", name="fk_eval_run_source_id_source", ondelete="CASCADE"),
        nullable=False,
    )
    physical_index_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey(
            "physical_index.id",
            name="fk_eval_run_physical_index_id_physical_index",
        ),
        nullable=False,
    )
    eval_suite_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("eval_suite.id", name="fk_eval_run_eval_suite_id_eval_suite"),
        nullable=False,
    )
    eval_suite_version: Mapped[int] = mapped_column(nullable=False)

    llm: Mapped[str] = mapped_column(String(128), nullable=False)
    rewrite_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    status: Mapped[EvalRunStatus] = mapped_column(
        String(32), nullable=False, default=EvalRunStatus.PENDING
    )
    execution_backend: Mapped[ExecutionBackend] = mapped_column(String(32), nullable=False)
    scores: Mapped[dict[str, Any] | None] = mapped_column(JSONType, nullable=True)

    mlflow_experiment_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    mlflow_run_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    mlflow_state: Mapped[MlflowSyncState] = mapped_column(
        String(32), nullable=False, default=MlflowSyncState.PENDING
    )

    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    triggered_by: Mapped[str | None] = mapped_column(String(128), nullable=True)
    triggered_by_kind: Mapped[TriggeredByKind | None] = mapped_column(String(32), nullable=True)

    eval_suite: Mapped[EvalSuite] = relationship("EvalSuite", back_populates="runs")
    results: Mapped[list[EvalResult]] = relationship(
        "EvalResult", back_populates="eval_run", cascade="all, delete-orphan"
    )


class EvalResult(Base):
    """A per-case result row for an eval run.

    Headline scores are projected onto ``EvalRun.scores`` and onto the source
    card. ``EvalResult`` rows give us the per-case data when we need to render
    a results table or back-fill MLflow.
    """

    __tablename__ = "eval_result"
    __table_args__ = (
        Index("ix_eval_result_eval_run_id", "eval_run_id"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=_new_uuid)
    eval_run_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey(
            "eval_run.id", name="fk_eval_result_eval_run_id_eval_run", ondelete="CASCADE"
        ),
        nullable=False,
    )
    case_id: Mapped[str] = mapped_column(String(128), nullable=False)
    metrics: Mapped[dict[str, Any]] = mapped_column(JSONType, nullable=False)
    payload: Mapped[dict[str, Any] | None] = mapped_column(JSONType, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )

    eval_run: Mapped[EvalRun] = relationship("EvalRun", back_populates="results")
