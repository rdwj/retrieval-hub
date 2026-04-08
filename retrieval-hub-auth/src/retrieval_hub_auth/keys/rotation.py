"""Key ring and JWKS construction for retrieval-hub-auth.

A ``KeyRing`` owns:

* Exactly one **signing key** (the active private key), and
* Zero or more **validator-only keys** (public keys trusted during a
  rotation window).

The ring exposes lookups used by the token issuer (get the signing key) and
by the token validator (get a public key by ``kid``), plus the JWKS
serialization used by the ``/.well-known/jwks.json`` route.
"""

from __future__ import annotations

import base64
from dataclasses import dataclass, field
from typing import Any

from cryptography.hazmat.primitives.asymmetric.rsa import RSAPublicKey

from retrieval_hub_auth.keys.loader import KeyMaterial


class KeyRingError(RuntimeError):
    """Raised when the key ring is misconfigured."""


@dataclass(slots=True)
class KeyRing:
    """Container for the service's active signing key and validator-only keys."""

    signing_key: KeyMaterial
    additional_keys: list[KeyMaterial] = field(default_factory=list)

    def __post_init__(self) -> None:
        """Validate the ring has a usable signing key."""
        if not self.signing_key.can_sign:
            raise KeyRingError("KeyRing signing_key must include a private key")

    @property
    def all_keys(self) -> list[KeyMaterial]:
        """All keys known to the ring, signing key first."""
        return [self.signing_key, *self.additional_keys]

    def get_public_key(self, kid: str) -> RSAPublicKey | None:
        """Return the public key matching the given ``kid``, or None if unknown."""
        for material in self.all_keys:
            if material.kid == kid:
                return material.public_key
        return None

    def contains(self, kid: str) -> bool:
        """True if the ring contains a key with the given ``kid``."""
        return self.get_public_key(kid) is not None


def _int_to_base64url(value: int) -> str:
    """Encode a non-negative integer as unpadded base64url per RFC 7518."""
    byte_length = (value.bit_length() + 7) // 8 or 1
    raw = value.to_bytes(byte_length, "big")
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _key_to_jwk(material: KeyMaterial) -> dict[str, str]:
    """Convert an ``RSAPublicKey`` into a JWK dict (RSA RS256 signing use)."""
    numbers = material.public_key.public_numbers()
    return {
        "kty": "RSA",
        "use": "sig",
        "alg": "RS256",
        "kid": material.kid,
        "n": _int_to_base64url(numbers.n),
        "e": _int_to_base64url(numbers.e),
    }


def build_jwks(ring: KeyRing) -> dict[str, Any]:
    """Return the JWKS document for the given key ring.

    The signing key appears first so naive consumers that don't honor
    ``kid`` still default to the active key.
    """
    return {"keys": [_key_to_jwk(material) for material in ring.all_keys]}
