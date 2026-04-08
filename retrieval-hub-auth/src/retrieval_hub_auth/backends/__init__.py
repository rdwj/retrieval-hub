"""IdP backend implementations for retrieval-hub-auth.

The backend layer is the part that answers "yes, this caller is authentic,
and here are their claims." v0 of retrieval-hub-auth only implements
``local``; ``openshift_oauth``, ``oidc_external``, and
``external_jwt_validator`` will be added in subsequent steps. See
``docs/auth.md`` and ``docs/integrations/README.md`` for the full design.
"""

from __future__ import annotations

from retrieval_hub_auth.backends.base import (
    AuthenticatedPrincipal,
    BackendError,
    DisabledClientError,
    IdPBackend,
    InvalidClientError,
    UnknownClientError,
)
from retrieval_hub_auth.backends.local import LocalBackend

__all__ = [
    "AuthenticatedPrincipal",
    "BackendError",
    "DisabledClientError",
    "IdPBackend",
    "InvalidClientError",
    "LocalBackend",
    "UnknownClientError",
]
