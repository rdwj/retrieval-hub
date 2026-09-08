"""Add ontology_mapping table

Revision ID: c7a9e2f1d834
Revises: b4378152f6b0
Create Date: 2026-09-08

"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c7a9e2f1d834"
down_revision: str | None = "b4378152f6b0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "ontology_mapping",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("canonical_name", sa.String(length=256), nullable=False),
        sa.Column("source_slug", sa.String(length=128), nullable=False),
        sa.Column("local_name", sa.String(length=256), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_ontology_mapping"),
        sa.UniqueConstraint(
            "canonical_name",
            "source_slug",
            "local_name",
            name="uq_ontology_mapping_canonical_source_local",
        ),
    )
    op.create_index("ix_canonical_name", "ontology_mapping", ["canonical_name"])
    op.create_index("ix_source_slug", "ontology_mapping", ["source_slug"])


def downgrade() -> None:
    op.drop_index("ix_source_slug", table_name="ontology_mapping")
    op.drop_index("ix_canonical_name", table_name="ontology_mapping")
    op.drop_table("ontology_mapping")
