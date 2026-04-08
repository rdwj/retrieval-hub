"""Key management for retrieval-hub-auth.

In production, signing keys are mounted from OpenShift Secrets at known file
paths. In development and tests we generate ephemeral RSA keys in-process.
Either way the service holds OpenSSL-backed key handles (via the
``cryptography`` package), never Python-implemented crypto, so the crypto
path stays FIPS-friendly.
"""

from __future__ import annotations

from retrieval_hub_auth.keys.loader import (
    KeyMaterial,
    generate_ephemeral_rsa_keypair,
    load_private_key_pem,
    load_public_key_pem,
)
from retrieval_hub_auth.keys.rotation import KeyRing, build_jwks

__all__ = [
    "KeyMaterial",
    "KeyRing",
    "build_jwks",
    "generate_ephemeral_rsa_keypair",
    "load_private_key_pem",
    "load_public_key_pem",
]
