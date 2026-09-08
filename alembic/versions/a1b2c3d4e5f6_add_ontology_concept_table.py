"""Add ontology_concept table

Revision ID: a1b2c3d4e5f6
Revises: c7a9e2f1d834
Create Date: 2026-09-08

"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a1b2c3d4e5f6"
down_revision: str | None = "c7a9e2f1d834"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "ontology_concept",
        sa.Column("name", sa.String(length=256), nullable=False),
        sa.Column("parent_name", sa.String(length=256), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("name", name="pk_ontology_concept"),
        sa.ForeignKeyConstraint(
            ["parent_name"],
            ["ontology_concept.name"],
            name="fk_ontology_concept_parent_name_ontology_concept",
        ),
    )
    op.create_index(
        "ix_ontology_concept_parent_name",
        "ontology_concept",
        ["parent_name"],
    )

    # Seed concepts from existing ontology_mapping canonical names.
    op.execute(
        "INSERT INTO ontology_concept (name, created_at) "
        "SELECT DISTINCT canonical_name, MIN(created_at) "
        "FROM ontology_mapping GROUP BY canonical_name"
    )


def downgrade() -> None:
    op.drop_index("ix_ontology_concept_parent_name", table_name="ontology_concept")
    op.drop_table("ontology_concept")
