"""Tests for ``EvalSuite``, ``EvalRun``, and MLflow lineage fields."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy.orm import Session

from retrieval_hub.models import EvalRun, EvalSuite
from retrieval_hub.models.enums import (
    EvalRunStatus,
    EvalSuiteFamily,
    ExecutionBackend,
    MlflowSyncState,
)
from tests.conftest import (
    make_eval_run,
    make_eval_suite,
    make_physical_index,
    make_recipe_version,
    make_source,
)


def test_eval_suite_persists_with_metric_set(session: Session) -> None:
    """An eval suite persists with its metric_set JSON intact."""
    suite = make_eval_suite(
        session,
        slug="rh-docs-eval",
        family=EvalSuiteFamily.DOCUMENT,
    )
    suite.metric_set = {
        "recall_at_5": {"type": "recall", "k": 5},
        "mrr": {"type": "mrr"},
    }
    suite.mlflow_experiment_name = "rh-docs-eval-prod"
    suite.mlflow_dataset_name = "rh-docs-cases-v1"
    suite.test_cases_storage_uri = "mlflow-datasets://rh-docs-cases-v1@2"
    session.commit()

    fetched = session.get(EvalSuite, suite.id)
    assert fetched is not None
    assert fetched.metric_set["recall_at_5"]["k"] == 5
    assert fetched.applies_to_family == EvalSuiteFamily.DOCUMENT
    assert fetched.mlflow_experiment_name == "rh-docs-eval-prod"


def test_eval_run_lifecycle(session: Session) -> None:
    """An eval run carries status, scores, and MLflow lineage pointers."""
    src = make_source(session)
    rv = make_recipe_version(session, src)
    pi = make_physical_index(session, src, rv)
    suite = make_eval_suite(session)
    run = make_eval_run(session, src, pi, suite, status=EvalRunStatus.PENDING)
    session.commit()

    # Promote the run through running -> completed.
    run.status = EvalRunStatus.RUNNING
    run.started_at = datetime.now(UTC)
    session.commit()

    run.status = EvalRunStatus.COMPLETED
    run.completed_at = datetime.now(UTC)
    run.scores = {"recall_at_5": 0.81, "mrr": 0.74}
    run.mlflow_experiment_id = "exp-123"
    run.mlflow_run_id = "run-456"
    run.mlflow_state = MlflowSyncState.SYNCED
    session.commit()

    fetched = session.get(EvalRun, run.id)
    assert fetched is not None
    assert fetched.status == EvalRunStatus.COMPLETED
    assert fetched.scores is not None
    assert fetched.scores["recall_at_5"] == 0.81
    assert fetched.mlflow_run_id == "run-456"
    assert fetched.mlflow_state == MlflowSyncState.SYNCED


def test_eval_run_failure_path(session: Session) -> None:
    """A failed eval run keeps the FAILED status and an unfinished MLflow state."""
    src = make_source(session)
    rv = make_recipe_version(session, src)
    pi = make_physical_index(session, src, rv)
    suite = make_eval_suite(session)
    run = make_eval_run(
        session,
        src,
        pi,
        suite,
        status=EvalRunStatus.RUNNING,
        execution_backend=ExecutionBackend.LLAMASTACK,
    )
    run.status = EvalRunStatus.FAILED
    run.mlflow_state = MlflowSyncState.FAILED
    session.commit()

    fetched = session.get(EvalRun, run.id)
    assert fetched is not None
    assert fetched.status == EvalRunStatus.FAILED
    assert fetched.execution_backend == ExecutionBackend.LLAMASTACK
    assert fetched.mlflow_state == MlflowSyncState.FAILED
