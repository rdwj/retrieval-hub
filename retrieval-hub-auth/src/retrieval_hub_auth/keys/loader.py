"""Load RSA key material for the auth service.

Public and private keys are read from PEM files on disk (in production,
mounted from OpenShift Secrets). For dev and test environments we generate
a fresh ephemeral keypair in-process.

Keys are represented as typed ``cryptography`` objects throughout the
service — never raw bytes — so the signing path always goes through
OS-level OpenSSL.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.asymmetric.rsa import (
    RSAPrivateKey,
    RSAPublicKey,
)


@dataclass(frozen=True, slots=True)
class KeyMaterial:
    """A single RSA keypair (or just a public key for validator-only entries).

    ``kid`` is the key identifier emitted in the JWT header and in the JWKS.
    It's derived deterministically from the public key material so the same
    key always has the same ``kid`` regardless of how it was loaded.
    """

    kid: str
    public_key: RSAPublicKey
    private_key: RSAPrivateKey | None

    @property
    def can_sign(self) -> bool:
        """True if this key material includes a private key and can sign."""
        return self.private_key is not None


def _compute_kid(public_key: RSAPublicKey) -> str:
    """Return a deterministic ``kid`` derived from the public key.

    We use the SHA-256 hash of the DER-encoded SubjectPublicKeyInfo,
    truncated to 16 hex characters. Deterministic so rotation can point at
    a predictable identifier; short so it stays readable in logs.
    """
    der = public_key.public_bytes(
        encoding=serialization.Encoding.DER,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    digest = hashlib.sha256(der).hexdigest()
    return digest[:16]


def load_private_key_pem(path: str | Path) -> KeyMaterial:
    """Load a PEM-encoded RSA private key from disk.

    Raises ``FileNotFoundError`` if the path does not exist and ``ValueError``
    if the file is not a valid unencrypted PEM private key.
    """
    pem_bytes = Path(path).read_bytes()
    private_key = serialization.load_pem_private_key(pem_bytes, password=None)
    if not isinstance(private_key, RSAPrivateKey):
        raise ValueError(f"Signing key at {path} is not an RSA private key")
    public_key = private_key.public_key()
    return KeyMaterial(
        kid=_compute_kid(public_key),
        public_key=public_key,
        private_key=private_key,
    )


def load_public_key_pem(path: str | Path) -> KeyMaterial:
    """Load a PEM-encoded RSA public key from disk (validator-only entry)."""
    pem_bytes = Path(path).read_bytes()
    public_key = serialization.load_pem_public_key(pem_bytes)
    if not isinstance(public_key, RSAPublicKey):
        raise ValueError(f"Public key at {path} is not an RSA public key")
    return KeyMaterial(
        kid=_compute_kid(public_key),
        public_key=public_key,
        private_key=None,
    )


def generate_ephemeral_rsa_keypair(key_size: int = 2048) -> KeyMaterial:
    """Generate a fresh RSA keypair for dev/test.

    Never use this in production: the private key exists only in process
    memory and is not persisted.
    """
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=key_size)
    public_key = private_key.public_key()
    return KeyMaterial(
        kid=_compute_kid(public_key),
        public_key=public_key,
        private_key=private_key,
    )


def private_key_to_pem_bytes(material: KeyMaterial) -> bytes:
    """Serialize a private key back to PEM (used by tests that need to mint keys)."""
    if material.private_key is None:
        raise ValueError("Key material has no private key to serialize")
    return material.private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )


def public_key_to_pem_bytes(material: KeyMaterial) -> bytes:
    """Serialize a public key to PEM (used by tests that need to mint keys)."""
    return material.public_key.public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
