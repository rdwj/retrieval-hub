"""Tests for the ``local`` IdP backend."""

from __future__ import annotations

import pytest

from retrieval_hub_auth.app_state import AppState
from retrieval_hub_auth.backends.base import (
    DisabledClientError,
    InvalidClientError,
    UnknownClientError,
)
from retrieval_hub_auth.backends.local import LocalBackend
from retrieval_hub_auth.db.models import IdentityKind


def test_register_and_authenticate_happy_path(app_state: AppState) -> None:
    backend: LocalBackend = app_state.backend  # type: ignore[assignment]
    backend.register_client(
        client_id="widget-agent",
        client_secret="s3cret-widget",
        client_name="Widget Agent",
        identity_kind=IdentityKind.AGENT,
        identity_groups=["widget-team"],
        default_scopes=["sources.list", "sources.read"],
    )

    principal = backend.authenticate_client("widget-agent", "s3cret-widget")
    assert principal.client_id == "widget-agent"
    assert principal.identity_kind == "agent"
    assert principal.identity_groups == ("widget-team",)
    assert principal.allowed_scopes == frozenset({"sources.list", "sources.read"})


def test_duplicate_registration_raises(app_state: AppState) -> None:
    backend: LocalBackend = app_state.backend  # type: ignore[assignment]
    backend.register_client(
        client_id="duplicate",
        client_secret="x",
        client_name="Dup",
        identity_kind=IdentityKind.AGENT,
    )
    with pytest.raises(ValueError):
        backend.register_client(
            client_id="duplicate",
            client_secret="y",
            client_name="Dup Again",
            identity_kind=IdentityKind.AGENT,
        )


def test_unknown_client_raises_unknown_client_error(app_state: AppState) -> None:
    backend: LocalBackend = app_state.backend  # type: ignore[assignment]
    with pytest.raises(UnknownClientError):
        backend.authenticate_client("ghost", "whatever")


def test_wrong_secret_raises_invalid_client_error(app_state: AppState) -> None:
    backend: LocalBackend = app_state.backend  # type: ignore[assignment]
    backend.register_client(
        client_id="alpha",
        client_secret="correct",
        client_name="Alpha",
        identity_kind=IdentityKind.AGENT,
    )
    with pytest.raises(InvalidClientError):
        backend.authenticate_client("alpha", "wrong")


def test_disabled_client_raises_disabled_client_error(app_state: AppState) -> None:
    backend: LocalBackend = app_state.backend  # type: ignore[assignment]
    backend.register_client(
        client_id="beta",
        client_secret="s3cret",
        client_name="Beta",
        identity_kind=IdentityKind.AGENT,
    )
    backend.disable_client("beta")
    with pytest.raises(DisabledClientError):
        backend.authenticate_client("beta", "s3cret")


def test_secret_is_stored_as_argon2_hash(app_state: AppState) -> None:
    backend: LocalBackend = app_state.backend  # type: ignore[assignment]
    backend.register_client(
        client_id="hashed-client",
        client_secret="plaintext-value",
        client_name="Hashed",
        identity_kind=IdentityKind.USER,
    )
    stored = backend.get_client("hashed-client")
    assert stored is not None
    assert stored.client_secret_hash != "plaintext-value"
    # Argon2id hashes start with $argon2id$
    assert stored.client_secret_hash.startswith("$argon2id$")


def test_disable_unknown_client_raises(app_state: AppState) -> None:
    backend: LocalBackend = app_state.backend  # type: ignore[assignment]
    with pytest.raises(UnknownClientError):
        backend.disable_client("no-such-client")


def test_last_used_at_updated_on_success(app_state: AppState) -> None:
    backend: LocalBackend = app_state.backend  # type: ignore[assignment]
    backend.register_client(
        client_id="tracker",
        client_secret="s3cret",
        client_name="Tracker",
        identity_kind=IdentityKind.AGENT,
    )
    before = backend.get_client("tracker")
    assert before is not None
    assert before.last_used_at is None

    backend.authenticate_client("tracker", "s3cret")

    after = backend.get_client("tracker")
    assert after is not None
    assert after.last_used_at is not None
