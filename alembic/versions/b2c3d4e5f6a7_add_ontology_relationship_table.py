"""Add ontology_relationship table

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-09-08

"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b2c3d4e5f6a7"
down_revision: str | None = "a1b2c3d4e5f6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "ontology_relationship",
        sa.Column("id", sa.Integer, autoincrement=True, nullable=False),
        sa.Column("source_concept", sa.String(length=256), nullable=False),
        sa.Column("relationship", sa.String(length=256), nullable=False),
        sa.Column("target_concept", sa.String(length=256), nullable=False),
        sa.Column("source_slug", sa.String(length=128), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_ontology_relationship"),
        sa.UniqueConstraint(
            "source_concept",
            "relationship",
            "target_concept",
            "source_slug",
            name="uq_ontology_rel_src_rel_tgt_slug",
        ),
    )
    op.create_index(
        "ix_ontology_relationship_source_concept",
        "ontology_relationship",
        ["source_concept"],
    )
    op.create_index(
        "ix_ontology_relationship_target_concept",
        "ontology_relationship",
        ["target_concept"],
    )
    op.create_index(
        "ix_ontology_relationship_source_slug",
        "ontology_relationship",
        ["source_slug"],
    )
    # Partial unique index for canonical (NULL source_slug) rows — PostgreSQL
    # unique constraints treat NULLs as distinct, so the constraint above
    # won't prevent duplicate canonical relationships.
    op.execute(
        "CREATE UNIQUE INDEX uq_ontology_rel_canonical "
        "ON ontology_relationship "
        "(source_concept, relationship, target_concept) "
        "WHERE source_slug IS NULL"
    )


def downgrade() -> None:
    op.execute(
        "DROP INDEX IF EXISTS uq_ontology_rel_canonical"
    )
    op.drop_index(
        "ix_ontology_relationship_source_slug",
        table_name="ontology_relationship",
    )
    op.drop_index(
        "ix_ontology_relationship_target_concept",
        table_name="ontology_relationship",
    )
    op.drop_index(
        "ix_ontology_relationship_source_concept",
        table_name="ontology_relationship",
    )
    op.drop_table("ontology_relationship")
