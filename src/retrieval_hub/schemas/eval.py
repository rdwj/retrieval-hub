"""Pydantic schemas for eval suites and eval runs."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from retrieval_hub.models.enums import (
    EvalRunStatus,
    EvalSuiteFamily,
    ExecutionBackend,
    MlflowSyncState,
    TriggeredByKind,
)


class EvalSuiteCreate(BaseModel):
    """Input shape for creating a new eval suite."""

    model_config = ConfigDict(extra="forbid")

    slug: str
    name: str
    applies_to_family: EvalSuiteFamily
    version_number: int = 1
    description: str | None = None
    metric_set: dict[str, Any]
    mlflow_experiment_name: str | None = None
    mlflow_dataset_name: str | None = None
    test_cases_storage_uri: str | None = None
    case_schema_id: str | None = None
    created_by: str | None = None


class EvalSuiteRead(BaseModel):
    """Read shape for an eval suite row."""

    model_config = ConfigDict(extra="forbid", from_attributes=True)

    id: str
    slug: str
    name: str
    applies_to_family: EvalSuiteFamily
    version_number: int
    description: str | None = None
    metric_set: dict[str, Any]
    mlflow_experiment_name: str | None = None
    mlflow_dataset_name: str | None = None
    test_cases_storage_uri: str | None = None
    case_schema_id: str | None = None
    created_at: datetime
    created_by: str | None = None


class EvalRunRead(BaseModel):
    """Read shape for an eval run row, including MLflow lineage pointers."""

    model_config = ConfigDict(extra="forbid", from_attributes=True)

    id: str
    source_id: str
    physical_index_id: str
    eval_suite_id: str
    eval_suite_version: int
    llm: str
    rewrite_enabled: bool
    status: EvalRunStatus
    execution_backend: ExecutionBackend
    scores: dict[str, Any] | None = Field(default=None)
    mlflow_experiment_id: str | None = None
    mlflow_run_id: str | None = None
    mlflow_state: MlflowSyncState
    started_at: datetime | None = None
    completed_at: datetime | None = None
    triggered_by: str | None = None
    triggered_by_kind: TriggeredByKind | None = None
