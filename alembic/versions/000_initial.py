"""Initial schema for the retrieval-hub catalog.

Creates every table defined in retrieval_hub.models. We deliberately use
JSON (via the JSONType abstraction) instead of database-native enum types so
the migration is portable across PostgreSQL and SQLite. The same migration
runs in production against Postgres and in tests against in-memory SQLite.

Revision ID: 000_initial
Revises:
Create Date: 2026-04-08
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from retrieval_hub.db.types import JSONType

# revision identifiers, used by Alembic.
revision: str = "000_initial"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create every table in dependency order."""
    # ------------------------------------------------------------------
    # source (no FKs out yet; the active_physical_index_id FK is added at
    # the end via use_alter so we can break the source <-> physical_index
    # cycle)
    # ------------------------------------------------------------------
    op.create_table(
        "source",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("slug", sa.String(length=128), nullable=False),
        sa.Column("name", sa.String(length=256), nullable=False),
        sa.Column("family", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("visibility", sa.String(length=32), nullable=False),
        sa.Column("description_short", sa.Text(), nullable=True),
        sa.Column("description_long", sa.Text(), nullable=True),
        sa.Column("owner_team", sa.String(length=128), nullable=True),
        sa.Column("owner_contacts", JSONType(), nullable=True),
        sa.Column("maintainers", JSONType(), nullable=True),
        sa.Column("recipe_version_id", sa.String(length=64), nullable=True),
        sa.Column("active_physical_index_id", sa.String(length=64), nullable=True),
        sa.Column("rewriter_metadata", JSONType(), nullable=True),
        sa.Column("agent_write_policy", JSONType(), nullable=True),
        sa.Column("access", JSONType(), nullable=True),
        sa.Column("lineage_origin", JSONType(), nullable=True),
        sa.Column("refresh_cadence", sa.String(length=64), nullable=True),
        sa.Column("last_refresh_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_by", sa.String(length=128), nullable=True),
        sa.Column("updated_by", sa.String(length=128), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_source"),
        sa.UniqueConstraint("slug", name="uq_source_slug"),
    )
    op.create_index("ix_source_status", "source", ["status"], unique=False)
    op.create_index("ix_source_family", "source", ["family"], unique=False)

    # ------------------------------------------------------------------
    # recipe_version (FK to source)
    # ------------------------------------------------------------------
    op.create_table(
        "recipe_version",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("source_id", sa.String(length=64), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("content", JSONType(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_by", sa.String(length=128), nullable=True),
        sa.ForeignKeyConstraint(
            ["source_id"],
            ["source.id"],
            name="fk_recipe_version_source_id_source",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_recipe_version"),
        sa.UniqueConstraint(
            "source_id",
            "version_number",
            name="uq_recipe_version_source_id_version_number",
        ),
    )
    op.create_index(
        "ix_recipe_version_source_id", "recipe_version", ["source_id"], unique=False
    )

    # source.recipe_version_id -> recipe_version.id (added now that
    # recipe_version exists)
    with op.batch_alter_table("source") as batch_op:
        batch_op.create_foreign_key(
            "fk_source_recipe_version_id_recipe_version",
            "recipe_version",
            ["recipe_version_id"],
            ["id"],
        )

    # ------------------------------------------------------------------
    # physical_index (FK to source + recipe_version)
    # ------------------------------------------------------------------
    op.create_table(
        "physical_index",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("source_id", sa.String(length=64), nullable=False),
        sa.Column("recipe_version_id", sa.String(length=64), nullable=False),
        sa.Column("backend_kind", sa.String(length=32), nullable=False),
        sa.Column("location", sa.String(length=512), nullable=False),
        sa.Column("built_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("health", sa.String(length=32), nullable=False),
        sa.Column("document_count", sa.Integer(), nullable=False),
        sa.Column("build_metadata", JSONType(), nullable=True),
        sa.ForeignKeyConstraint(
            ["source_id"],
            ["source.id"],
            name="fk_physical_index_source_id_source",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["recipe_version_id"],
            ["recipe_version.id"],
            name="fk_physical_index_recipe_version_id_recipe_version",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_physical_index"),
    )
    op.create_index(
        "ix_physical_index_source_id", "physical_index", ["source_id"], unique=False
    )
    op.create_index(
        "ix_physical_index_recipe_version_id",
        "physical_index",
        ["recipe_version_id"],
        unique=False,
    )

    # source.active_physical_index_id -> physical_index.id (deferred FK).
    with op.batch_alter_table("source") as batch_op:
        batch_op.create_foreign_key(
            "fk_source_active_physical_index_id_physical_index",
            "physical_index",
            ["active_physical_index_id"],
            ["id"],
        )

    # ------------------------------------------------------------------
    # sample_prompt
    # ------------------------------------------------------------------
    op.create_table(
        "sample_prompt",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("source_id", sa.String(length=64), nullable=False),
        sa.Column("applies_to_llm_family", sa.String(length=128), nullable=False),
        sa.Column("role", sa.String(length=32), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["source_id"],
            ["source.id"],
            name="fk_sample_prompt_source_id_source",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_sample_prompt"),
    )
    op.create_index(
        "ix_sample_prompt_source_id", "sample_prompt", ["source_id"], unique=False
    )

    # ------------------------------------------------------------------
    # rewrite_prompt_ref
    # ------------------------------------------------------------------
    op.create_table(
        "rewrite_prompt_ref",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("source_id", sa.String(length=64), nullable=False),
        sa.Column("prompt_slug", sa.String(length=256), nullable=False),
        sa.Column("active_version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["source_id"],
            ["source.id"],
            name="fk_rewrite_prompt_ref_source_id_source",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_rewrite_prompt_ref"),
    )
    op.create_index(
        "ix_rewrite_prompt_ref_source_id",
        "rewrite_prompt_ref",
        ["source_id"],
        unique=False,
    )

    # ------------------------------------------------------------------
    # eval_suite
    # ------------------------------------------------------------------
    op.create_table(
        "eval_suite",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("slug", sa.String(length=128), nullable=False),
        sa.Column("name", sa.String(length=256), nullable=False),
        sa.Column("applies_to_family", sa.String(length=32), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("metric_set", JSONType(), nullable=False),
        sa.Column("mlflow_experiment_name", sa.String(length=256), nullable=True),
        sa.Column("mlflow_dataset_name", sa.String(length=256), nullable=True),
        sa.Column("test_cases_storage_uri", sa.String(length=512), nullable=True),
        sa.Column("case_schema_id", sa.String(length=128), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_by", sa.String(length=128), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_eval_suite"),
        sa.UniqueConstraint(
            "slug", "version_number", name="uq_eval_suite_slug_version_number"
        ),
    )

    # ------------------------------------------------------------------
    # eval_run (FKs to source, physical_index, eval_suite)
    # ------------------------------------------------------------------
    op.create_table(
        "eval_run",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("source_id", sa.String(length=64), nullable=False),
        sa.Column("physical_index_id", sa.String(length=64), nullable=False),
        sa.Column("eval_suite_id", sa.String(length=64), nullable=False),
        sa.Column("eval_suite_version", sa.Integer(), nullable=False),
        sa.Column("llm", sa.String(length=128), nullable=False),
        sa.Column("rewrite_enabled", sa.Boolean(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("execution_backend", sa.String(length=32), nullable=False),
        sa.Column("scores", JSONType(), nullable=True),
        sa.Column("mlflow_experiment_id", sa.String(length=128), nullable=True),
        sa.Column("mlflow_run_id", sa.String(length=128), nullable=True),
        sa.Column("mlflow_state", sa.String(length=32), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("triggered_by", sa.String(length=128), nullable=True),
        sa.Column("triggered_by_kind", sa.String(length=32), nullable=True),
        sa.ForeignKeyConstraint(
            ["source_id"],
            ["source.id"],
            name="fk_eval_run_source_id_source",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["physical_index_id"],
            ["physical_index.id"],
            name="fk_eval_run_physical_index_id_physical_index",
        ),
        sa.ForeignKeyConstraint(
            ["eval_suite_id"],
            ["eval_suite.id"],
            name="fk_eval_run_eval_suite_id_eval_suite",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_eval_run"),
    )
    op.create_index("ix_eval_run_source_id", "eval_run", ["source_id"], unique=False)
    op.create_index(
        "ix_eval_run_physical_index_id", "eval_run", ["physical_index_id"], unique=False
    )
    op.create_index(
        "ix_eval_run_eval_suite_id", "eval_run", ["eval_suite_id"], unique=False
    )
    op.create_index("ix_eval_run_status", "eval_run", ["status"], unique=False)

    # ------------------------------------------------------------------
    # eval_result
    # ------------------------------------------------------------------
    op.create_table(
        "eval_result",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("eval_run_id", sa.String(length=64), nullable=False),
        sa.Column("case_id", sa.String(length=128), nullable=False),
        sa.Column("metrics", JSONType(), nullable=False),
        sa.Column("payload", JSONType(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["eval_run_id"],
            ["eval_run.id"],
            name="fk_eval_result_eval_run_id_eval_run",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_eval_result"),
    )
    op.create_index(
        "ix_eval_result_eval_run_id", "eval_result", ["eval_run_id"], unique=False
    )

    # ------------------------------------------------------------------
    # ingestion_run
    # ------------------------------------------------------------------
    op.create_table(
        "ingestion_run",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("source_id", sa.String(length=64), nullable=False),
        sa.Column("recipe_version_id", sa.String(length=64), nullable=False),
        sa.Column("refresh_mode", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("stages_completed", JSONType(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("triggered_by", sa.String(length=128), nullable=True),
        sa.Column("triggered_by_kind", sa.String(length=32), nullable=True),
        sa.Column("result_manifest", JSONType(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["source_id"],
            ["source.id"],
            name="fk_ingestion_run_source_id_source",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["recipe_version_id"],
            ["recipe_version.id"],
            name="fk_ingestion_run_recipe_version_id_recipe_version",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_ingestion_run"),
    )
    op.create_index(
        "ix_ingestion_run_source_id", "ingestion_run", ["source_id"], unique=False
    )
    op.create_index(
        "ix_ingestion_run_status", "ingestion_run", ["status"], unique=False
    )

    # ------------------------------------------------------------------
    # audit_record
    # ------------------------------------------------------------------
    op.create_table(
        "audit_record",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("identity_sub", sa.String(length=256), nullable=False),
        sa.Column("identity_kind", sa.String(length=32), nullable=False),
        sa.Column("action", sa.String(length=128), nullable=False),
        sa.Column("source_id", sa.String(length=64), nullable=True),
        sa.Column("details", JSONType(), nullable=True),
        sa.Column("request_id", sa.String(length=128), nullable=True),
        sa.ForeignKeyConstraint(
            ["source_id"],
            ["source.id"],
            name="fk_audit_record_source_id_source",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_audit_record"),
    )
    op.create_index(
        "ix_audit_record_occurred_at", "audit_record", ["occurred_at"], unique=False
    )
    op.create_index(
        "ix_audit_record_source_id", "audit_record", ["source_id"], unique=False
    )
    op.create_index("ix_audit_record_action", "audit_record", ["action"], unique=False)


def downgrade() -> None:
    """Drop every table in reverse dependency order."""
    op.drop_index("ix_audit_record_action", table_name="audit_record")
    op.drop_index("ix_audit_record_source_id", table_name="audit_record")
    op.drop_index("ix_audit_record_occurred_at", table_name="audit_record")
    op.drop_table("audit_record")

    op.drop_index("ix_ingestion_run_status", table_name="ingestion_run")
    op.drop_index("ix_ingestion_run_source_id", table_name="ingestion_run")
    op.drop_table("ingestion_run")

    op.drop_index("ix_eval_result_eval_run_id", table_name="eval_result")
    op.drop_table("eval_result")

    op.drop_index("ix_eval_run_status", table_name="eval_run")
    op.drop_index("ix_eval_run_eval_suite_id", table_name="eval_run")
    op.drop_index("ix_eval_run_physical_index_id", table_name="eval_run")
    op.drop_index("ix_eval_run_source_id", table_name="eval_run")
    op.drop_table("eval_run")

    op.drop_table("eval_suite")

    op.drop_index("ix_rewrite_prompt_ref_source_id", table_name="rewrite_prompt_ref")
    op.drop_table("rewrite_prompt_ref")

    op.drop_index("ix_sample_prompt_source_id", table_name="sample_prompt")
    op.drop_table("sample_prompt")

    # Break the source <-> physical_index cycle before dropping either side.
    with op.batch_alter_table("source") as batch_op:
        batch_op.drop_constraint(
            "fk_source_active_physical_index_id_physical_index", type_="foreignkey"
        )

    op.drop_index("ix_physical_index_recipe_version_id", table_name="physical_index")
    op.drop_index("ix_physical_index_source_id", table_name="physical_index")
    op.drop_table("physical_index")

    with op.batch_alter_table("source") as batch_op:
        batch_op.drop_constraint(
            "fk_source_recipe_version_id_recipe_version", type_="foreignkey"
        )

    op.drop_index("ix_recipe_version_source_id", table_name="recipe_version")
    op.drop_table("recipe_version")

    op.drop_index("ix_source_family", table_name="source")
    op.drop_index("ix_source_status", table_name="source")
    op.drop_table("source")
