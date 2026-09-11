"""Add ontology_query_metric table

Revision ID: d4e5f6a7b8c9
Revises: c3d4e5f6a7b8
Create Date: 2026-09-10

"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "d4e5f6a7b8c9"
down_revision: str | None = "c3d4e5f6a7b8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "ontology_query_metric",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("mapping_id", sa.Integer, nullable=False, index=True),
        sa.Column("source_slug", sa.String(128), nullable=False, index=True),
        sa.Column("canonical_name", sa.String(256), nullable=False, index=True),
        sa.Column("hit_count", sa.Integer, nullable=False),
        sa.Column("top_score", sa.Float, nullable=True),
        sa.Column(
            "query_timestamp",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
            index=True,
        ),
    )


def downgrade() -> None:
    op.drop_table("ontology_query_metric")
