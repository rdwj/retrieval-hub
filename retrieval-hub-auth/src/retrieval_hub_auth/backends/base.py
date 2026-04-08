"""The IdP backend protocol and the exceptions its callers can expect.

Every backend implementation (``local``, ``openshift_oauth``,
``oidc_external``, ``external_jwt_validator``) implements this protocol.
The ``/token`` route does not know which backend is active; it just calls
``authenticate_client`` and translates the result into a JWT.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol


class BackendError(Exception):
    """Base class for all IdP-backend errors."""


class UnknownClientError(BackendError):
    """Raised when the client_id is not recognized by the backend."""


class InvalidClientError(BackendError):
    """Raised when the client_id is known but the secret does not match."""


class DisabledClientError(BackendError):
    """Raised when the client is known but has been administratively disabled."""


@dataclass(frozen=True, slots=True)
class AuthenticatedPrincipal:
    """The result of a successful client authentication.

    This is a backend-agnostic view of the identity the token issuer will
    mint a JWT for. The backend is responsible for populating ``identity_kind``
    correctly — the downstream ``admin.write`` guard in the issuer relies
    on this field being truthful.
    """

    client_id: str
    identity_kind: str  # "user" | "agent" | "service" | "client"
    identity_groups: tuple[str, ...] = field(default_factory=tuple)
    tenant: str = "default"
    allowed_scopes: frozenset[str] = field(default_factory=frozenset)
    max_token_lifetime_seconds: int = 900


class IdPBackend(Protocol):
    """Protocol every IdP backend implements."""

    name: str

    def authenticate_client(self, client_id: str, client_secret: str) -> AuthenticatedPrincipal:
        """Validate a client credential and return the authenticated principal.

        Raises ``UnknownClientError`` if the client_id isn't recognized,
        ``InvalidClientError`` if the secret doesn't match, and
        ``DisabledClientError`` if the client has been disabled.
        """
        ...
