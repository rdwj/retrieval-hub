"""ORM models owned by retrieval-hub-auth.

Two tables:

* ``client_registrations`` — the ``local`` IdP backend's client table.
  Stores ``client_id``, the Argon2id hash of the client secret, the claim
  metadata the issuer needs to build a retrieval-hub JWT, and the scopes the
  client is allowed to request.
* ``token_issuance_audit`` — append-only audit log of every successful
  token issuance. Failed issuances go to the application log (where they're
  signal for operators), not this table.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from sqlalchemy import Boolean, DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from retrieval_hub_auth.db.base import Base, JSONType


class IdentityKind(StrEnum):
    """Identity kind values mirror the ``rh_identity_kind`` claim.

    The set matches ``retrieval_hub.models.identity.IdentityKind`` in the
    core library — we redefine it here so this peer component has no hard
    import of the core library at scaffold time.
    """

    USER = "user"
    AGENT = "agent"
    SERVICE = "service"
    CLIENT = "client"


class ClientRegistration(Base):
    """A client credential registration in the ``local`` IdP backend.

    Only used when ``RETRIEVAL_HUB_AUTH_BACKEND=local``. Other backends
    validate against an external IdP and never consult this table.
    """

    __tablename__ = "client_registrations"

    client_id: Mapped[str] = mapped_column(String(length=128), primary_key=True)
    client_secret_hash: Mapped[str] = mapped_column(String(length=512), nullable=False)
    client_name: Mapped[str] = mapped_column(String(length=256), nullable=False)
    client_description: Mapped[str | None] = mapped_column(String(length=1024), nullable=True)

    identity_kind: Mapped[str] = mapped_column(String(length=32), nullable=False)
    identity_groups: Mapped[list[str]] = mapped_column(JSONType(), nullable=False, default=list)

    tenant: Mapped[str] = mapped_column(String(length=128), nullable=False, default="default")
    default_scopes: Mapped[list[str]] = mapped_column(JSONType(), nullable=False, default=list)

    max_token_lifetime_seconds: Mapped[int] = mapped_column(Integer, nullable=False, default=900)

    disabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class TokenIssuanceRecord(Base):
    """Append-only audit record for every successful token issuance.

    Failures are intentionally not stored here — they live in the structured
    application log where they're more useful as operational signal. This
    table is *only* successful issuances and is treated as append-only at
    the application layer (no UPDATE or DELETE path exists in code).
    """

    __tablename__ = "token_issuance_audit"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    jti: Mapped[str] = mapped_column(String(length=64), nullable=False, index=True)
    client_id: Mapped[str] = mapped_column(String(length=128), nullable=False, index=True)
    identity_kind: Mapped[str] = mapped_column(String(length=32), nullable=False)
    scopes_issued: Mapped[list[str]] = mapped_column(JSONType(), nullable=False, default=list)
    tenant: Mapped[str] = mapped_column(String(length=128), nullable=False)
    issued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    client_ip: Mapped[str | None] = mapped_column(String(length=64), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String(length=512), nullable=True)
    backend_used: Mapped[str] = mapped_column(String(length=64), nullable=False)
