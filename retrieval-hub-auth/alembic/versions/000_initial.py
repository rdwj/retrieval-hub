"""Initial schema for retrieval-hub-auth.

Creates the ``client_registrations`` table (used by the ``local`` IdP
backend) and the append-only ``token_issuance_audit`` table.

We use JSON (via the JSONType abstraction in
``retrieval_hub_auth.db.base``) rather than database-native enum types so
this migration runs unchanged against PostgreSQL in production and
in-memory SQLite in tests.

Revision ID: 000_initial
Revises:
Create Date: 2026-04-08
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from retrieval_hub_auth.db.base import JSONType

# revision identifiers, used by Alembic.
revision: str = "000_initial"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create the auth service's two tables."""
    op.create_table(
        "client_registrations",
        sa.Column("client_id", sa.String(length=128), nullable=False),
        sa.Column("client_secret_hash", sa.String(length=512), nullable=False),
        sa.Column("client_name", sa.String(length=256), nullable=False),
        sa.Column("client_description", sa.String(length=1024), nullable=True),
        sa.Column("identity_kind", sa.String(length=32), nullable=False),
        sa.Column("identity_groups", JSONType(), nullable=False),
        sa.Column("tenant", sa.String(length=128), nullable=False),
        sa.Column("default_scopes", JSONType(), nullable=False),
        sa.Column("max_token_lifetime_seconds", sa.Integer(), nullable=False),
        sa.Column("disabled", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("client_id", name="pk_client_registrations"),
    )

    op.create_table(
        "token_issuance_audit",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("jti", sa.String(length=64), nullable=False),
        sa.Column("client_id", sa.String(length=128), nullable=False),
        sa.Column("identity_kind", sa.String(length=32), nullable=False),
        sa.Column("scopes_issued", JSONType(), nullable=False),
        sa.Column("tenant", sa.String(length=128), nullable=False),
        sa.Column("issued_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("client_ip", sa.String(length=64), nullable=True),
        sa.Column("user_agent", sa.String(length=512), nullable=True),
        sa.Column("backend_used", sa.String(length=64), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_token_issuance_audit"),
    )
    op.create_index(
        op.f("ix_token_issuance_audit_jti"),
        "token_issuance_audit",
        ["jti"],
        unique=False,
    )
    op.create_index(
        op.f("ix_token_issuance_audit_client_id"),
        "token_issuance_audit",
        ["client_id"],
        unique=False,
    )


def downgrade() -> None:
    """Drop the auth service's tables."""
    op.drop_index(
        op.f("ix_token_issuance_audit_client_id"), table_name="token_issuance_audit"
    )
    op.drop_index(
        op.f("ix_token_issuance_audit_jti"), table_name="token_issuance_audit"
    )
    op.drop_table("token_issuance_audit")
    op.drop_table("client_registrations")
