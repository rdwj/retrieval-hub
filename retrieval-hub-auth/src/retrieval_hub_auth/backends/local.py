"""The ``local`` IdP backend.

Authenticates clients against rows in the ``client_registrations`` table.
Secrets are stored as Argon2id hashes. The backend is deliberately small:
it does lookups, verifies secrets, and translates rows into the
backend-agnostic ``AuthenticatedPrincipal`` shape. It does **not** build
JWTs or evaluate scope policy — that's the issuer's job.

This backend is the right choice for development, demos, and air-gapped
clusters. Production environments should use ``openshift_oauth``,
``oidc_external``, or ``external_jwt_validator``.
"""

from __future__ import annotations

from datetime import UTC, datetime

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from retrieval_hub_auth.backends.base import (
    AuthenticatedPrincipal,
    DisabledClientError,
    IdPBackend,
    InvalidClientError,
    UnknownClientError,
)
from retrieval_hub_auth.db.models import ClientRegistration, IdentityKind


class LocalBackend(IdPBackend):
    """Postgres-backed client registration store."""

    name = "local"

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        """Construct the backend with a session factory for its database."""
        self._session_factory = session_factory
        self._hasher = PasswordHasher()

    # ------------------------------------------------------------------
    # Registration (admin surface)
    # ------------------------------------------------------------------

    def register_client(
        self,
        *,
        client_id: str,
        client_secret: str,
        client_name: str,
        identity_kind: IdentityKind,
        identity_groups: list[str] | None = None,
        default_scopes: list[str] | None = None,
        tenant: str = "default",
        max_token_lifetime_seconds: int = 900,
        description: str | None = None,
    ) -> None:
        """Create a new client registration.

        The secret is hashed with Argon2id before persistence. Raises
        ``ValueError`` if a client with the given id already exists.
        """
        hashed = self._hasher.hash(client_secret)
        with self._session_factory() as session:
            existing = session.get(ClientRegistration, client_id)
            if existing is not None:
                raise ValueError(f"Client id '{client_id}' is already registered")
            row = ClientRegistration(
                client_id=client_id,
                client_secret_hash=hashed,
                client_name=client_name,
                client_description=description,
                identity_kind=identity_kind.value,
                identity_groups=list(identity_groups or []),
                tenant=tenant,
                default_scopes=list(default_scopes or []),
                max_token_lifetime_seconds=max_token_lifetime_seconds,
                disabled=False,
                created_at=datetime.now(tz=UTC),
                last_used_at=None,
            )
            session.add(row)
            session.commit()

    def disable_client(self, client_id: str) -> None:
        """Mark a client disabled. Future authentication attempts will fail."""
        with self._session_factory() as session:
            row = session.get(ClientRegistration, client_id)
            if row is None:
                raise UnknownClientError(f"Unknown client_id '{client_id}'")
            row.disabled = True
            session.commit()

    def get_client(self, client_id: str) -> ClientRegistration | None:
        """Return the stored registration row, or None if not found."""
        with self._session_factory() as session:
            return session.get(ClientRegistration, client_id)

    # ------------------------------------------------------------------
    # IdPBackend protocol
    # ------------------------------------------------------------------

    def authenticate_client(self, client_id: str, client_secret: str) -> AuthenticatedPrincipal:
        """Validate credentials and return the principal shape.

        Looks up the row, verifies the Argon2id hash, rejects disabled
        clients, and updates ``last_used_at`` on success.
        """
        with self._session_factory() as session:
            row = session.execute(
                select(ClientRegistration).where(ClientRegistration.client_id == client_id)
            ).scalar_one_or_none()

            if row is None:
                raise UnknownClientError(f"Unknown client_id '{client_id}'")

            try:
                self._hasher.verify(row.client_secret_hash, client_secret)
            except VerifyMismatchError as exc:
                raise InvalidClientError("Client secret does not match") from exc

            if row.disabled:
                raise DisabledClientError(f"Client '{client_id}' is disabled")

            row.last_used_at = datetime.now(tz=UTC)
            session.commit()

            return AuthenticatedPrincipal(
                client_id=row.client_id,
                identity_kind=row.identity_kind,
                identity_groups=tuple(row.identity_groups or []),
                tenant=row.tenant,
                allowed_scopes=frozenset(row.default_scopes or []),
                max_token_lifetime_seconds=row.max_token_lifetime_seconds,
            )
