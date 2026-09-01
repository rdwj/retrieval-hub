"""Shared pytest fixtures and factories for the retrieval-hub test suite.

Tests run against an in-memory SQLite database. The schema is built by running
the project's Alembic migrations against the test engine, so we exercise the
real migration code path on every test run rather than relying on
``Base.metadata.create_all``.
"""

from __future__ import annotations

import os
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from retrieval_hub.models import (
    EvalRun,
    EvalSuite,
    Identity,
    PhysicalIndex,
    RecipeVersion,
    Source,
)
from retrieval_hub.models.enums import (
    AccessVisibility,
    EvalRunStatus,
    EvalSuiteFamily,
    ExecutionBackend,
    IndexHealth,
    MlflowSyncState,
    PhysicalIndexBackend,
    SourceFamily,
    SourceStatus,
    WriteMode,
)

ALEMBIC_INI = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "alembic.ini")
)
ALEMBIC_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "alembic"))


# ---------------------------------------------------------------------------
# Engine / session fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def db_url(tmp_path_factory: pytest.TempPathFactory) -> str:
    """Return a per-session SQLite file URL.

    We use a file (not ``:memory:``) so that the alembic process can talk to
    the same database that the test session opens.
    """
    db_file = tmp_path_factory.mktemp("retrieval-hub-tests") / "test.sqlite"
    return f"sqlite:///{db_file}"


@pytest.fixture(scope="session")
def engine(db_url: str) -> Iterator[Engine]:
    """Build a SQLAlchemy engine and apply alembic migrations."""
    os.environ["RETRIEVAL_HUB_DB_URL"] = db_url
    cfg = Config(ALEMBIC_INI)
    cfg.set_main_option("script_location", ALEMBIC_DIR)
    cfg.set_main_option("sqlalchemy.url", db_url)
    command.upgrade(cfg, "head")
    eng = create_engine(db_url, future=True)
    try:
        yield eng
    finally:
        eng.dispose()


@pytest.fixture()
def session(engine: Engine) -> Iterator[Session]:
    """Provide a clean session per test, rolled back at the end."""
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
    sess = factory()
    try:
        yield sess
    finally:
        # Roll back any pending state and clear out rows the test created so
        # the next test starts from a clean schema. We delete in FK-safe order.
        sess.rollback()
        for table in [
            "audit_record",
            "ingestion_run",
            "eval_result",
            "eval_run",
            "eval_suite",
            "rewrite_prompt_ref",
            "model_endpoint",
            "sample_prompt",
        ]:
            sess.execute(_delete_all(table))
        # Break the source <-> physical_index cycle before deleting either side.
        sess.execute(
            _raw("UPDATE source SET active_physical_index_id = NULL")
        )
        for table in ["physical_index", "recipe_version", "source"]:
            sess.execute(_delete_all(table))
        sess.commit()
        sess.close()


def _delete_all(table: str) -> Any:
    """Return a textual ``DELETE FROM <table>`` statement."""
    from sqlalchemy import text

    return text(f"DELETE FROM {table}")


def _raw(sql: str) -> Any:
    """Return a raw textual SQL statement."""
    from sqlalchemy import text

    return text(sql)


# ---------------------------------------------------------------------------
# Data factories
# ---------------------------------------------------------------------------


def _utcnow() -> datetime:
    return datetime.now(UTC)


def make_source(
    session: Session,
    *,
    slug: str | None = None,
    name: str = "Test Source",
    family: SourceFamily = SourceFamily.DOCUMENT,
    status: SourceStatus = SourceStatus.DRAFT,
    visibility: AccessVisibility = AccessVisibility.PUBLIC,
    access: dict[str, Any] | None = None,
    agent_write_policy: dict[str, Any] | None = None,
    rewriter_metadata: dict[str, Any] | None = None,
) -> Source:
    """Insert a Source row with sensible defaults and return it."""
    src = Source(
        id=str(uuid.uuid4()),
        slug=slug or f"src-{uuid.uuid4().hex[:8]}",
        name=name,
        family=family,
        status=status,
        visibility=visibility,
        access=access,
        agent_write_policy=agent_write_policy,
        rewriter_metadata=rewriter_metadata,
        created_at=_utcnow(),
        updated_at=_utcnow(),
    )
    session.add(src)
    session.flush()
    return src


def make_recipe_version(
    session: Session,
    source: Source,
    *,
    version_number: int = 1,
    content: dict[str, Any] | None = None,
) -> RecipeVersion:
    """Insert a RecipeVersion bound to ``source``."""
    rv = RecipeVersion(
        id=str(uuid.uuid4()),
        source_id=source.id,
        version_number=version_number,
        content=content or {"parser": {"kind": "docling"}, "chunker": {"size": 512}},
        created_at=_utcnow(),
    )
    session.add(rv)
    session.flush()
    return rv


def make_physical_index(
    session: Session,
    source: Source,
    recipe_version: RecipeVersion,
    *,
    backend_kind: PhysicalIndexBackend = PhysicalIndexBackend.PGVECTOR,
    location: str = "idx_test_v1",
    health: IndexHealth = IndexHealth.OK,
    document_count: int = 0,
) -> PhysicalIndex:
    """Insert a PhysicalIndex bound to ``source`` + ``recipe_version``."""
    pi = PhysicalIndex(
        id=str(uuid.uuid4()),
        source_id=source.id,
        recipe_version_id=recipe_version.id,
        backend_kind=backend_kind,
        location=location,
        built_at=_utcnow(),
        health=health,
        document_count=document_count,
    )
    session.add(pi)
    session.flush()
    return pi


def make_eval_suite(
    session: Session,
    *,
    slug: str | None = None,
    family: EvalSuiteFamily = EvalSuiteFamily.DOCUMENT,
    version_number: int = 1,
) -> EvalSuite:
    """Insert an EvalSuite row."""
    suite = EvalSuite(
        id=str(uuid.uuid4()),
        slug=slug or f"suite-{uuid.uuid4().hex[:6]}",
        name="Test suite",
        applies_to_family=family,
        version_number=version_number,
        metric_set={"recall_at_5": {"type": "recall", "k": 5}},
        created_at=_utcnow(),
    )
    session.add(suite)
    session.flush()
    return suite


def make_eval_run(
    session: Session,
    source: Source,
    physical_index: PhysicalIndex,
    eval_suite: EvalSuite,
    *,
    status: EvalRunStatus = EvalRunStatus.PENDING,
    execution_backend: ExecutionBackend = ExecutionBackend.NATIVE,
) -> EvalRun:
    """Insert an EvalRun row in the requested status."""
    run = EvalRun(
        id=str(uuid.uuid4()),
        source_id=source.id,
        physical_index_id=physical_index.id,
        eval_suite_id=eval_suite.id,
        eval_suite_version=eval_suite.version_number,
        llm="granite-3.3-8b-instruct",
        rewrite_enabled=False,
        status=status,
        execution_backend=execution_backend,
        mlflow_state=MlflowSyncState.PENDING,
    )
    session.add(run)
    session.flush()
    return run


def make_model_endpoint(
    session: Session,
    *,
    model_name: str = "test-model/test-embed-v1",
    endpoint_url: str = "http://test-embedding:8000",
    status: str = "unknown",
) -> "ModelEndpoint":
    """Insert a ModelEndpoint row with sensible defaults."""
    from retrieval_hub.models.model_endpoint import ModelEndpoint

    ep = ModelEndpoint(
        id=str(uuid.uuid4()),
        model_name=model_name,
        endpoint_url=endpoint_url,
        status=status,
        registered_at=_utcnow(),
        updated_at=_utcnow(),
    )
    session.add(ep)
    session.flush()
    return ep


# ---------------------------------------------------------------------------
# Identity factories
# ---------------------------------------------------------------------------


def make_identity(
    *,
    sub: str = "client:test-agent",
    kind: str = "agent",
    groups: tuple[str, ...] = (),
    scopes: frozenset[str] = frozenset(),
    email: str | None = None,
) -> Identity:
    """Build an ``Identity`` for policy tests."""
    return Identity(sub=sub, kind=kind, groups=groups, scopes=scopes, email=email)  # type: ignore[arg-type]


# Re-export for convenience
__all__ = [
    "WriteMode",
    "make_eval_run",
    "make_eval_suite",
    "make_identity",
    "make_model_endpoint",
    "make_physical_index",
    "make_recipe_version",
    "make_source",
]
