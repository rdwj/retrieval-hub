"""Add semantic_context column to source

Revision ID: 8d676bcbdc15
Revises: eb5372940775
Create Date: 2026-08-19 08:45:22.368727

"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = '8d676bcbdc15'
down_revision: str | None = 'eb5372940775'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table('source', schema=None) as batch_op:
        batch_op.add_column(sa.Column('semantic_context', sa.JSON(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('source', schema=None) as batch_op:
        batch_op.drop_column('semantic_context')
