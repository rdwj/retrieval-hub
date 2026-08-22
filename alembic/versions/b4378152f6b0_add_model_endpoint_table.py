"""Add model_endpoint table

Revision ID: b4378152f6b0
Revises: 8d676bcbdc15
Create Date: 2026-08-22

"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b4378152f6b0"
down_revision: str | None = "8d676bcbdc15"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "model_endpoint",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("model_name", sa.String(length=256), nullable=False),
        sa.Column("endpoint_url", sa.String(length=512), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("last_probed", sa.DateTime(timezone=True), nullable=True),
        sa.Column("registered_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_model_endpoint"),
        sa.UniqueConstraint("model_name", name="uq_model_endpoint_model_name"),
    )


def downgrade() -> None:
    op.drop_table("model_endpoint")
