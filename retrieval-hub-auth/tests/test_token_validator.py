"""Tests for the TokenValidator — the contract downstream consumers depend on."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from retrieval_hub_auth.backends.base import AuthenticatedPrincipal
from retrieval_hub_auth.keys.loader import generate_ephemeral_rsa_keypair
from retrieval_hub_auth.keys.rotation import KeyRing
from retrieval_hub_auth.tokens.issuer import TokenIssuer
from retrieval_hub_auth.tokens.validator import (
    InvalidAudienceError,
    InvalidIssuerError,
    InvalidSignatureError,
    MalformedTokenError,
    TokenExpiredError,
    TokenValidator,
    UnknownKeyError,
)

ISSUER = "https://auth.retrieval-hub.test/"
AUDIENCE = "retrieval-hub"


def _principal() -> AuthenticatedPrincipal:
    return AuthenticatedPrincipal(
        client_id="validator-test",
        identity_kind="agent",
        identity_groups=("agents",),
        tenant="default",
        allowed_scopes=frozenset(
            {"sources.list", "sources.read", "sources.query", "rewrite.invoke"}
        ),
        max_token_lifetime_seconds=900,
    )


def _issuer(key_ring: KeyRing) -> TokenIssuer:
    return TokenIssuer(
        key_ring=key_ring,
        issuer=ISSUER,
        audience=AUDIENCE,
        default_lifetime_seconds=900,
    )


def _validator(key_ring: KeyRing) -> TokenValidator:
    return TokenValidator(
        key_ring=key_ring,
        issuer=ISSUER,
        audience=AUDIENCE,
    )


def test_valid_token_is_parsed(key_ring: KeyRing) -> None:
    issued = _issuer(key_ring).issue(_principal())
    identity = _validator(key_ring).validate(issued.access_token)

    assert identity.sub == "agent:validator-test"
    assert identity.kind == "agent"
    assert identity.groups == ("agents",)
    assert "sources.list" in identity.scopes
    assert identity.tenant == "default"
    assert identity.jti == issued.claims.jti


def test_expired_token_rejected(key_ring: KeyRing) -> None:
    in_the_past = datetime(2024, 1, 1, tzinfo=UTC)
    issued = _issuer(key_ring).issue(_principal(), now=in_the_past)

    now = in_the_past + timedelta(seconds=10_000)
    with pytest.raises(TokenExpiredError):
        _validator(key_ring).validate(issued.access_token, now=now)


def test_wrong_audience_rejected(key_ring: KeyRing) -> None:
    issued = _issuer(key_ring).issue(_principal())
    mismatch_validator = TokenValidator(
        key_ring=key_ring,
        issuer=ISSUER,
        audience="something-else",
    )
    with pytest.raises(InvalidAudienceError):
        mismatch_validator.validate(issued.access_token)


def test_wrong_issuer_rejected(key_ring: KeyRing) -> None:
    issued = _issuer(key_ring).issue(_principal())
    mismatch_validator = TokenValidator(
        key_ring=key_ring,
        issuer="https://auth.attacker.test/",
        audience=AUDIENCE,
    )
    with pytest.raises(InvalidIssuerError):
        mismatch_validator.validate(issued.access_token)


def test_tampered_signature_rejected(key_ring: KeyRing) -> None:
    issued = _issuer(key_ring).issue(_principal())
    header, payload, signature = issued.access_token.split(".")
    # Flip a character in the signature segment
    swap = "A" if signature[0] != "A" else "B"
    tampered = f"{header}.{payload}.{swap}{signature[1:]}"

    with pytest.raises((InvalidSignatureError, MalformedTokenError)):
        _validator(key_ring).validate(tampered)


def test_previously_active_key_still_validates(key_ring: KeyRing) -> None:
    """A token signed by a previous signing key validates during a rotation window.

    Scenario: key-A was the signing key and issued a token. Later, key-B
    took over as the signing key. Key-A is kept in the ring as an
    additional validator-only key. The old token must still validate.
    """
    old_signing_key = key_ring.signing_key
    old_issuer = _issuer(key_ring)
    issued = old_issuer.issue(_principal())

    # Rotate: make a new ring with a new signing key, but keep the old
    # public key for validation.
    new_signing_key = generate_ephemeral_rsa_keypair()
    rotated_ring = KeyRing(
        signing_key=new_signing_key,
        additional_keys=[old_signing_key],
    )

    identity = _validator(rotated_ring).validate(issued.access_token)
    assert identity.sub == "agent:validator-test"


def test_token_signed_by_unknown_key_rejected(key_ring: KeyRing) -> None:
    other_ring = KeyRing(signing_key=generate_ephemeral_rsa_keypair())
    issued = _issuer(other_ring).issue(_principal())

    with pytest.raises(UnknownKeyError):
        _validator(key_ring).validate(issued.access_token)


def test_malformed_token_rejected(key_ring: KeyRing) -> None:
    with pytest.raises(MalformedTokenError):
        _validator(key_ring).validate("not.a.jwt.at.all")


def test_validator_has_scope_and_in_group_helpers(key_ring: KeyRing) -> None:
    issued = _issuer(key_ring).issue(_principal())
    identity = _validator(key_ring).validate(issued.access_token)
    assert identity.has_scope("sources.list")
    assert not identity.has_scope("admin.write")
    assert identity.in_group("agents")
    assert not identity.in_group("admins")
