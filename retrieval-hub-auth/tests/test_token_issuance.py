"""Unit tests for the token issuer, independent of the HTTP surface."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from retrieval_hub_auth.backends.base import AuthenticatedPrincipal
from retrieval_hub_auth.keys.rotation import KeyRing
from retrieval_hub_auth.tokens.issuer import (
    AdminWriteForbiddenError,
    InvalidScopeError,
    TokenIssuer,
)


def _make_issuer(key_ring: KeyRing) -> TokenIssuer:
    return TokenIssuer(
        key_ring=key_ring,
        issuer="https://auth.retrieval-hub.test/",
        audience="retrieval-hub",
        default_lifetime_seconds=900,
    )


def _agent_principal(scopes: list[str] | None = None) -> AuthenticatedPrincipal:
    return AuthenticatedPrincipal(
        client_id="test-agent",
        identity_kind="agent",
        identity_groups=("agents",),
        tenant="default",
        allowed_scopes=frozenset(
            scopes or ["sources.list", "sources.read", "sources.query", "rewrite.invoke"]
        ),
        max_token_lifetime_seconds=900,
    )


def _user_principal(scopes: list[str]) -> AuthenticatedPrincipal:
    return AuthenticatedPrincipal(
        client_id="admin-user",
        identity_kind="user",
        identity_groups=("admins",),
        tenant="default",
        allowed_scopes=frozenset(scopes),
        max_token_lifetime_seconds=900,
    )


def test_issued_claims_match_documented_shape(key_ring: KeyRing) -> None:
    issuer = _make_issuer(key_ring)
    principal = _agent_principal()
    result = issuer.issue(principal)
    claims = result.claims

    assert claims.iss == "https://auth.retrieval-hub.test/"
    assert claims.aud == "retrieval-hub"
    assert claims.sub == "agent:test-agent"
    assert claims.rh_identity_kind == "agent"
    assert claims.rh_identity_groups == ["agents"]
    assert claims.rh_tenant == "default"
    assert claims.jti.startswith("tok_")
    assert claims.iat == claims.nbf
    assert claims.exp - claims.iat == 900
    # Scope is space-separated and sorted
    scopes = set(claims.scope.split())
    assert scopes == {
        "sources.list",
        "sources.read",
        "sources.query",
        "rewrite.invoke",
    }


def test_lifetime_is_min_of_default_and_principal_max(key_ring: KeyRing) -> None:
    issuer = _make_issuer(key_ring)
    principal = AuthenticatedPrincipal(
        client_id="short-lived",
        identity_kind="agent",
        identity_groups=(),
        tenant="default",
        allowed_scopes=frozenset({"sources.list"}),
        max_token_lifetime_seconds=60,
    )
    result = issuer.issue(principal)
    assert result.claims.exp - result.claims.iat == 60


def test_jti_is_unique_across_multiple_issuances(key_ring: KeyRing) -> None:
    issuer = _make_issuer(key_ring)
    principal = _agent_principal()
    jtis = {issuer.issue(principal).claims.jti for _ in range(25)}
    assert len(jtis) == 25


def test_requested_scope_outside_vocabulary_rejected(key_ring: KeyRing) -> None:
    issuer = _make_issuer(key_ring)
    principal = _agent_principal()
    with pytest.raises(InvalidScopeError):
        issuer.issue(principal, requested_scopes=frozenset({"made.up"}))


def test_requested_scope_not_allowed_for_principal_rejected(key_ring: KeyRing) -> None:
    issuer = _make_issuer(key_ring)
    principal = _agent_principal()
    with pytest.raises(InvalidScopeError):
        # sources.write is in the vocabulary, but this agent doesn't have it
        issuer.issue(principal, requested_scopes=frozenset({"sources.write"}))


def test_agent_admin_write_rejected_by_issuer(key_ring: KeyRing) -> None:
    """The hard rule: admin.write must never be issued to an agent identity.

    Even if the IdP backend has (incorrectly) placed admin.write in the
    principal's allowed scopes, the issuer refuses.
    """
    issuer = _make_issuer(key_ring)
    principal = AuthenticatedPrincipal(
        client_id="bad-agent",
        identity_kind="agent",
        identity_groups=("agents",),
        tenant="default",
        allowed_scopes=frozenset({"sources.list", "admin.write"}),
        max_token_lifetime_seconds=900,
    )
    with pytest.raises(AdminWriteForbiddenError):
        issuer.issue(principal, requested_scopes=frozenset({"admin.write"}))


def test_service_admin_write_rejected_by_issuer(key_ring: KeyRing) -> None:
    """Same rule applies to service-kind identities."""
    issuer = _make_issuer(key_ring)
    principal = AuthenticatedPrincipal(
        client_id="bad-service",
        identity_kind="service",
        identity_groups=(),
        tenant="default",
        allowed_scopes=frozenset({"admin.write"}),
        max_token_lifetime_seconds=900,
    )
    with pytest.raises(AdminWriteForbiddenError):
        issuer.issue(principal, requested_scopes=frozenset({"admin.write"}))


def test_user_can_receive_admin_write(key_ring: KeyRing) -> None:
    """The guard does not apply to user-kind identities."""
    issuer = _make_issuer(key_ring)
    principal = _user_principal(["sources.list", "admin.read", "admin.write"])
    result = issuer.issue(principal, requested_scopes=frozenset({"admin.write"}))
    assert "admin.write" in result.claims.scope


def test_default_scopes_on_empty_request(key_ring: KeyRing) -> None:
    issuer = _make_issuer(key_ring)
    principal = _agent_principal(scopes=["sources.list", "sources.read"])
    result = issuer.issue(principal, requested_scopes=None)
    assert set(result.claims.scope.split()) == {"sources.list", "sources.read"}


def test_issued_at_uses_provided_clock(key_ring: KeyRing) -> None:
    issuer = _make_issuer(key_ring)
    principal = _agent_principal()
    fixed = datetime(2026, 4, 8, 12, 0, 0, tzinfo=UTC)
    result = issuer.issue(principal, now=fixed)
    assert result.claims.iat == int(fixed.timestamp())
    assert result.claims.exp == int((fixed + timedelta(seconds=900)).timestamp())
