"""Typed representation of a validated JWT's identity claims.

This is **not** a database model. It's the typed shape that the policy module
operates against, populated by whichever consumer (MCP, UI BFF, CLI) decoded
the JWT. Keeping it as a plain dataclass means the core library does not have
to import any auth-service-specific types.

See ``docs/auth.md`` for the JWT shape this is derived from.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

IdentityKind = Literal["user", "agent", "service", "client"]


@dataclass(frozen=True, slots=True)
class Identity:
    """The identity claims relevant to source-level access decisions.

    Attributes mirror the ``rh_*`` claims documented in ``docs/auth.md``. The
    constructor is intentionally minimal: callers should populate it from a
    validated JWT and never from raw user input.
    """

    sub: str
    kind: IdentityKind
    groups: tuple[str, ...] = field(default_factory=tuple)
    scopes: frozenset[str] = field(default_factory=frozenset)
    tenant: str = "default"
    request_id: str | None = None
    email: str | None = None

    def has_scope(self, scope: str) -> bool:
        """Return True if the identity carries the given scope."""
        return scope in self.scopes

    def in_group(self, group: str) -> bool:
        """Return True if the identity is a member of the given group."""
        return group in self.groups

    @property
    def email_domain(self) -> str | None:
        """Extract the domain part of the email, or None."""
        if self.email and "@" in self.email:
            return self.email.rsplit("@", 1)[1].lower()
        return None
