"""Token issuer for retrieval-hub-auth.

The issuer is the component that knows how to turn an ``AuthenticatedPrincipal``
(from the IdP backend) into a signed retrieval-hub JWT. It is also the
single place where the **admin.write guard** is enforced in code:

    admin.write must NEVER be issued to an identity whose rh_identity_kind
    is ``agent`` or ``service``.

This rule is the technical mechanism behind "MCP is not a catalog mutation
surface for agents." See ``docs/auth.md`` §"Token shape" for the full
rationale.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from authlib.jose import JsonWebToken
from sqlalchemy.orm import Session, sessionmaker
from ulid import ULID

from retrieval_hub_auth.backends.base import AuthenticatedPrincipal
from retrieval_hub_auth.db.models import TokenIssuanceRecord
from retrieval_hub_auth.keys.rotation import KeyRing
from retrieval_hub_auth.tokens.claims import (
    NON_ADMIN_IDENTITY_KINDS,
    SCOPE_ADMIN_WRITE,
    SCOPES_ALL,
    TokenClaims,
)

JWT_ALG = "RS256"

_jwt = JsonWebToken([JWT_ALG])


class IssuanceError(Exception):
    """Base class for issuance failures."""


class InvalidScopeError(IssuanceError):
    """Raised when the caller requests a scope outside the known vocabulary."""


class AdminWriteForbiddenError(IssuanceError):
    """Raised when an agent or service identity requests ``admin.write``.

    This is the code-level enforcement of the hard rule in ``docs/auth.md``:
    regardless of what the IdP backend or claim mapping says, ``admin.write``
    is never projected onto an agent or service identity.
    """


@dataclass(frozen=True, slots=True)
class IssuedToken:
    """The result of a successful issuance: the JWT plus the claims it carries."""

    access_token: str
    claims: TokenClaims


class TokenIssuer:
    """Build and sign retrieval-hub JWTs.

    The issuer holds a reference to the service's ``KeyRing`` (the active
    signing key) and to a session factory for writing audit records. It
    does not talk to any IdP backend directly; callers pass in an already-
    authenticated principal.
    """

    def __init__(
        self,
        *,
        key_ring: KeyRing,
        issuer: str,
        audience: str,
        default_lifetime_seconds: int,
        session_factory: sessionmaker[Session] | None = None,
        backend_name: str = "local",
    ) -> None:
        """Construct the issuer with key material and policy configuration."""
        self._key_ring = key_ring
        self._issuer = issuer
        self._audience = audience
        self._default_lifetime = default_lifetime_seconds
        self._session_factory = session_factory
        self._backend_name = backend_name

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def issue(
        self,
        principal: AuthenticatedPrincipal,
        *,
        requested_scopes: frozenset[str] | None = None,
        caller_app: str | None = None,
        request_id: str | None = None,
        client_ip: str | None = None,
        user_agent: str | None = None,
        now: datetime | None = None,
    ) -> IssuedToken:
        """Issue a signed JWT for the given principal.

        Validates the requested scopes, applies the admin.write guard,
        builds the claim set, signs it with the active key, and writes an
        audit record.
        """
        granted_scopes = self._resolve_scopes(principal, requested_scopes)
        now = now or datetime.now(tz=UTC)
        iat = int(now.timestamp())
        lifetime = min(self._default_lifetime, principal.max_token_lifetime_seconds)
        exp = iat + lifetime
        jti = f"tok_{ULID()}"

        claims = TokenClaims(
            iss=self._issuer,
            aud=self._audience,
            sub=f"{principal.identity_kind}:{principal.client_id}",
            iat=iat,
            nbf=iat,
            exp=exp,
            jti=jti,
            scope=" ".join(sorted(granted_scopes)),
            rh_identity_kind=principal.identity_kind,
            rh_identity_groups=list(principal.identity_groups),
            rh_tenant=principal.tenant,
            rh_caller_app=caller_app,
            rh_request_id=request_id,
        )
        access_token = self._sign(claims)

        if self._session_factory is not None:
            self._write_audit_record(
                claims=claims,
                client_id=principal.client_id,
                client_ip=client_ip,
                user_agent=user_agent,
            )

        return IssuedToken(access_token=access_token, claims=claims)

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _resolve_scopes(
        self,
        principal: AuthenticatedPrincipal,
        requested: frozenset[str] | None,
    ) -> frozenset[str]:
        """Apply the scope policy (intersection, validation, admin.write guard)."""
        if requested is None or len(requested) == 0:
            resolved = frozenset(principal.allowed_scopes)
        else:
            unknown = requested - SCOPES_ALL
            if unknown:
                raise InvalidScopeError(
                    f"Requested scope(s) not in the retrieval-hub vocabulary: {sorted(unknown)}"
                )
            not_allowed = requested - principal.allowed_scopes
            if not_allowed:
                raise InvalidScopeError(
                    f"Requested scope(s) not permitted for this client: {sorted(not_allowed)}"
                )
            resolved = frozenset(requested)

        # Hard admin.write guard. Applied after the scope is otherwise
        # resolved so any attempt to grant it to a non-human identity is
        # observable, not silently dropped.
        if SCOPE_ADMIN_WRITE in resolved and principal.identity_kind in NON_ADMIN_IDENTITY_KINDS:
            raise AdminWriteForbiddenError(
                f"admin.write may not be issued to identity kind "
                f"'{principal.identity_kind}' (client_id={principal.client_id})"
            )

        return resolved

    def _sign(self, claims: TokenClaims) -> str:
        """RS256-sign the given claim set with the active signing key."""
        payload: dict[str, Any] = claims.model_dump(exclude_none=True)
        header = {"alg": JWT_ALG, "kid": self._key_ring.signing_key.kid}
        private_key = self._key_ring.signing_key.private_key
        assert private_key is not None  # guarded by KeyRing.__post_init__
        token_bytes: bytes = _jwt.encode(header, payload, private_key)
        return token_bytes.decode("ascii")

    def _write_audit_record(
        self,
        *,
        claims: TokenClaims,
        client_id: str,
        client_ip: str | None,
        user_agent: str | None,
    ) -> None:
        """Persist an append-only audit row for the issued token."""
        assert self._session_factory is not None
        record = TokenIssuanceRecord(
            jti=claims.jti,
            client_id=client_id,
            identity_kind=claims.rh_identity_kind,
            scopes_issued=claims.scope.split() if claims.scope else [],
            tenant=claims.rh_tenant,
            issued_at=datetime.fromtimestamp(claims.iat, tz=UTC),
            expires_at=datetime.fromtimestamp(claims.exp, tz=UTC),
            client_ip=client_ip,
            user_agent=user_agent,
            backend_used=self._backend_name,
        )
        with self._session_factory() as session:
            session.add(record)
            session.commit()
