"""Runtime configuration for retrieval-hub-auth.

All settings are read from environment variables with the
``RETRIEVAL_HUB_AUTH_`` prefix. The default values are developer-friendly
(SQLite in-memory database, ephemeral keys); production deploys must set
every path- or URL-based setting explicitly.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class AuthSettings(BaseSettings):
    """Pydantic settings model for the auth service.

    Values come from environment variables prefixed with
    ``RETRIEVAL_HUB_AUTH_``. A ``.env`` file in the working directory is
    honored for local development.
    """

    model_config = SettingsConfigDict(
        env_prefix="RETRIEVAL_HUB_AUTH_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Database
    db_url: str = Field(
        default="sqlite+pysqlite:///:memory:",
        description="SQLAlchemy URL for the auth service's Postgres schema.",
    )

    # Token issuer + audience
    issuer: str = Field(
        default="https://auth.retrieval-hub.local/",
        description="The ``iss`` claim emitted on every token we issue.",
    )
    audience: str = Field(
        default="retrieval-hub",
        description="The ``aud`` claim emitted on every token we issue.",
    )

    # Key material paths (mounted from OpenShift Secrets in production)
    signing_key_path: str | None = Field(
        default=None,
        description="Path to the active PEM-encoded private key used to sign tokens.",
    )
    additional_public_key_paths: str = Field(
        default="",
        description=(
            "Comma-separated list of PEM-encoded public key paths. These keys "
            "are still trusted for validation during rotation windows."
        ),
    )

    # Token lifetime
    default_token_lifetime_seconds: int = Field(
        default=900,
        description="Default ``expires_in`` for issued tokens. Per-client overrides allowed.",
        ge=60,
        le=86400,
    )

    # IdP backend selector (only "local" is implemented in this scaffold)
    backend: Literal["local", "openshift_oauth", "oidc_external", "external_jwt_validator"] = Field(
        default="local",
        description="Which IdP backend to use. Only ``local`` is implemented in v0.",
    )

    # Logging
    log_level: str = Field(
        default="INFO",
        description="Python logging level for the service logger.",
    )

    # Rate limiting (in-memory in this scaffold; real backend comes later)
    rate_limit_per_client_per_minute: int = Field(
        default=60,
        description="Per-client rate limit for the /token endpoint.",
        ge=1,
    )

    # Test / dev toggle: generate ephemeral keys at startup if none configured
    generate_ephemeral_keys_if_missing: bool = Field(
        default=True,
        description="If True and no signing key is configured, generate an in-process RSA key.",
    )


@lru_cache(maxsize=1)
def get_settings() -> AuthSettings:
    """Return the cached AuthSettings singleton."""
    return AuthSettings()


def reset_settings_cache() -> None:
    """Clear the settings cache (for tests that mutate environment variables)."""
    get_settings.cache_clear()
