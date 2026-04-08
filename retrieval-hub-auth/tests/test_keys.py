"""Tests for the key loader and key ring helpers."""

from __future__ import annotations

from pathlib import Path

import pytest

from retrieval_hub_auth.keys.loader import (
    generate_ephemeral_rsa_keypair,
    load_private_key_pem,
    load_public_key_pem,
    private_key_to_pem_bytes,
    public_key_to_pem_bytes,
)
from retrieval_hub_auth.keys.rotation import KeyRing, KeyRingError, build_jwks


def test_generate_ephemeral_produces_signing_key() -> None:
    material = generate_ephemeral_rsa_keypair()
    assert material.can_sign
    assert material.kid  # non-empty
    # kid is deterministic per public key
    assert len(material.kid) == 16


def test_load_private_key_from_disk(tmp_path: Path) -> None:
    generated = generate_ephemeral_rsa_keypair()
    pem_path = tmp_path / "signing.pem"
    pem_path.write_bytes(private_key_to_pem_bytes(generated))

    loaded = load_private_key_pem(pem_path)
    assert loaded.can_sign
    assert loaded.kid == generated.kid


def test_load_public_key_from_disk(tmp_path: Path) -> None:
    generated = generate_ephemeral_rsa_keypair()
    pem_path = tmp_path / "public.pem"
    pem_path.write_bytes(public_key_to_pem_bytes(generated))

    loaded = load_public_key_pem(pem_path)
    assert not loaded.can_sign
    assert loaded.kid == generated.kid


def test_key_ring_requires_signing_key() -> None:
    generated = generate_ephemeral_rsa_keypair()
    # Construct a validator-only KeyMaterial by removing the private key.
    from retrieval_hub_auth.keys.loader import KeyMaterial

    pub_only = KeyMaterial(
        kid=generated.kid,
        public_key=generated.public_key,
        private_key=None,
    )
    with pytest.raises(KeyRingError):
        KeyRing(signing_key=pub_only)


def test_key_ring_get_public_key_finds_rotation_key() -> None:
    active = generate_ephemeral_rsa_keypair()
    retired = generate_ephemeral_rsa_keypair()
    ring = KeyRing(signing_key=active, additional_keys=[retired])

    assert ring.get_public_key(active.kid) is not None
    assert ring.get_public_key(retired.kid) is not None
    assert ring.get_public_key("bogus") is None
    assert ring.contains(retired.kid)


def test_build_jwks_contains_every_key() -> None:
    active = generate_ephemeral_rsa_keypair()
    retired = generate_ephemeral_rsa_keypair()
    ring = KeyRing(signing_key=active, additional_keys=[retired])

    jwks = build_jwks(ring)
    assert len(jwks["keys"]) == 2
    kids = [k["kid"] for k in jwks["keys"]]
    assert kids[0] == active.kid  # signing key first
    assert retired.kid in kids
    for entry in jwks["keys"]:
        assert entry["kty"] == "RSA"
        assert entry["alg"] == "RS256"
        assert entry["use"] == "sig"
