"""JWT validator used by downstream consumers of retrieval-hub-auth.

The validator is the authoritative reference implementation of "what does
a valid retrieval-hub JWT look like, and how do you extract the typed
identity from it." ``retrieval-hub-mcp``, the UI BFF, and the SDK all
import from this module so that nobody reinvents the validation logic.

The validator's output is a ``ValidatedIdentity`` — a shape very close to
``retrieval_hub.models.identity.Identity`` in the core library but owned
by the auth service so the core library doesn't have to import anything
from here.
"""

from __future__ import annotations

import base64
import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Literal

from authlib.jose import JsonWebToken
from authlib.jose.errors import (
    BadSignatureError,
    DecodeError,
    JoseError,
)

from retrieval_hub_auth.keys.rotation import KeyRing

IdentityKindLiteral = Literal["user", "agent", "service", "client"]

_jwt = JsonWebToken(["RS256"])


class ValidationError(Exception):
    """Base class for JWT validation errors."""


class TokenExpiredError(ValidationError):
    """Raised when the token's ``exp`` is in the past."""


class TokenNotYetValidError(ValidationError):
    """Raised when the token's ``nbf`` is in the future."""


class InvalidAudienceError(ValidationError):
    """Raised when the ``aud`` claim does not match the expected audience."""


class InvalidIssuerError(ValidationError):
    """Raised when the ``iss`` claim does not match the expected issuer."""


class InvalidSignatureError(ValidationError):
    """Raised when the token signature does not verify against the expected key."""


class UnknownKeyError(ValidationError):
    """Raised when the token was signed by a key the ring does not contain."""


class MalformedTokenError(ValidationError):
    """Raised when the token cannot be decoded at all (not three segments, bad base64)."""


@dataclass(frozen=True, slots=True)
class ValidatedIdentity:
    """Typed identity extracted from a validated JWT.

    Mirrors ``retrieval_hub.models.identity.Identity`` in the core library
    but owned by the auth service. The core library holds its own copy so
    neither side has to import from the other.
    """

    sub: str
    kind: IdentityKindLiteral
    groups: tuple[str, ...] = field(default_factory=tuple)
    scopes: frozenset[str] = field(default_factory=frozenset)
    tenant: str = "default"
    request_id: str | None = None
    caller_app: str | None = None
    jti: str = ""
    issued_at: int = 0
    expires_at: int = 0

    def has_scope(self, scope: str) -> bool:
        """Return True if the identity carries the given scope."""
        return scope in self.scopes

    def in_group(self, group: str) -> bool:
        """Return True if the identity is a member of the given group."""
        return group in self.groups


def _b64url_decode(segment: str) -> bytes:
    """Decode a base64url segment, adding any missing padding."""
    padding = "=" * (-len(segment) % 4)
    return base64.urlsafe_b64decode(segment + padding)


def _peek_header(token: str) -> dict[str, Any]:
    """Return the decoded JWT header without verifying the signature."""
    try:
        header_segment = token.split(".")[0]
        raw = _b64url_decode(header_segment)
        header: dict[str, Any] = json.loads(raw)
        return header
    except (IndexError, ValueError, json.JSONDecodeError) as exc:
        raise MalformedTokenError(f"Token is not a well-formed JWT: {exc}") from exc


class TokenValidator:
    """Validator for retrieval-hub JWTs.

    Constructed with the same ``KeyRing``, issuer, and audience that the
    issuer was configured with. In practice, the MCP server creates one
    of these at startup from the auth service's JWKS endpoint — but for
    tests and in-process use we take the key ring directly.
    """

    def __init__(
        self,
        *,
        key_ring: KeyRing,
        issuer: str,
        audience: str,
        clock_skew_seconds: int = 30,
    ) -> None:
        """Store the validation policy."""
        self._key_ring = key_ring
        self._issuer = issuer
        self._audience = audience
        self._clock_skew_seconds = clock_skew_seconds

    def validate(self, token: str, *, now: datetime | None = None) -> ValidatedIdentity:
        """Validate ``token`` and return the typed identity it carries.

        Raises one of the :class:`ValidationError` subclasses on any
        validation failure. Successful validation returns a
        ``ValidatedIdentity`` built from the token's ``rh_*`` claims.
        """
        header = _peek_header(token)
        kid = header.get("kid")
        if not isinstance(kid, str):
            raise MalformedTokenError("Token header is missing a ``kid`` field")

        public_key = self._key_ring.get_public_key(kid)
        if public_key is None:
            raise UnknownKeyError(f"Token was signed with unknown key id '{kid}'")

        try:
            claims = _jwt.decode(token, public_key)
        except BadSignatureError as exc:
            raise InvalidSignatureError("Token signature did not verify") from exc
        except DecodeError as exc:
            raise MalformedTokenError(f"Token could not be decoded: {exc}") from exc
        except JoseError as exc:  # pragma: no cover - defensive
            raise ValidationError(str(exc)) from exc

        now_dt = now or datetime.now(tz=UTC)
        now_ts = int(now_dt.timestamp())
        self._check_issuer(claims)
        self._check_audience(claims)
        self._check_expiry(claims, now_ts)
        self._check_not_before(claims, now_ts)

        return self._build_identity(claims)

    # ------------------------------------------------------------------
    # Claim checks
    # ------------------------------------------------------------------

    def _check_issuer(self, claims: dict[str, Any]) -> None:
        if claims.get("iss") != self._issuer:
            raise InvalidIssuerError(f"Expected issuer {self._issuer!r}, got {claims.get('iss')!r}")

    def _check_audience(self, claims: dict[str, Any]) -> None:
        aud = claims.get("aud")
        if isinstance(aud, list):
            if self._audience not in aud:
                raise InvalidAudienceError(f"Expected audience {self._audience!r} in {aud!r}")
        elif aud != self._audience:
            raise InvalidAudienceError(f"Expected audience {self._audience!r}, got {aud!r}")

    def _check_expiry(self, claims: dict[str, Any], now_ts: int) -> None:
        exp = claims.get("exp")
        if not isinstance(exp, int):
            raise ValidationError("Token is missing a numeric ``exp`` claim")
        if now_ts > exp + self._clock_skew_seconds:
            raise TokenExpiredError(f"Token expired at {exp}, current time is {now_ts}")

    def _check_not_before(self, claims: dict[str, Any], now_ts: int) -> None:
        nbf = claims.get("nbf")
        if isinstance(nbf, int) and now_ts + self._clock_skew_seconds < nbf:
            raise TokenNotYetValidError(f"Token not valid until {nbf}, current time is {now_ts}")

    def _build_identity(self, claims: dict[str, Any]) -> ValidatedIdentity:
        kind_raw = claims.get("rh_identity_kind")
        if kind_raw not in ("user", "agent", "service", "client"):
            raise ValidationError(f"Token has unexpected rh_identity_kind: {kind_raw!r}")

        groups_raw = claims.get("rh_identity_groups") or []
        if not isinstance(groups_raw, list):
            raise ValidationError("rh_identity_groups claim must be a list")

        scope_raw = claims.get("scope") or ""
        if not isinstance(scope_raw, str):
            raise ValidationError("scope claim must be a string")
        scopes = frozenset(s for s in scope_raw.split() if s)

        return ValidatedIdentity(
            sub=str(claims.get("sub", "")),
            kind=kind_raw,
            groups=tuple(str(g) for g in groups_raw),
            scopes=scopes,
            tenant=str(claims.get("rh_tenant", "default")),
            request_id=claims.get("rh_request_id"),
            caller_app=claims.get("rh_caller_app"),
            jti=str(claims.get("jti", "")),
            issued_at=int(claims.get("iat", 0)),
            expires_at=int(claims.get("exp", 0)),
        )
