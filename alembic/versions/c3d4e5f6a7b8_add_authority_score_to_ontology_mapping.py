"""Add authority_score to ontology_mapping

Revision ID: c3d4e5f6a7b8
Revises: b2c3d4e5f6a7
Create Date: 2026-09-08

"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c3d4e5f6a7b8"
down_revision: str | None = "b2c3d4e5f6a7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "ontology_mapping",
        sa.Column(
            "authority_score",
            sa.Float,
            nullable=False,
            server_default="1.0",
        ),
    )


def downgrade() -> None:
    op.drop_column("ontology_mapping", "authority_score")
