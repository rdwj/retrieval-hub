"""Tests for ``policy.writes.can_write``.

The two-gate rule from docs/catalog.md is the contract under test:
1. The source's agent_write_policy must allow the requested write_mode.
2. The caller must hold the required scope (default ``sources.write``).
3. If the policy lists allowed_groups, the caller must intersect them.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from retrieval_hub.models.enums import SourceStatus, WriteMode
from retrieval_hub.policy import can_write
from tests.conftest import make_identity, make_source


def _writeable_source(
    session: Session,
    *,
    write_modes: list[str],
    allowed_groups: list[str] | None = None,
    scope_required: str = "sources.write",
    allowed: bool = True,
    status: SourceStatus = SourceStatus.PUBLISHED,
):
    """Create a source whose write policy is ready for testing."""
    return make_source(
        session,
        status=status,
        agent_write_policy={
            "allowed": allowed,
            "scope_required": scope_required,
            "write_modes": write_modes,
            "allowed_groups": allowed_groups or [],
        },
    )


def test_default_policy_denies_writes(session: Session) -> None:
    """A source with no agent_write_policy denies all writes by default."""
    src = make_source(session, status=SourceStatus.PUBLISHED)
    identity = make_identity(kind="agent", scopes=frozenset({"sources.write"}))
    assert can_write(identity, src, WriteMode.APPEND) is False


def test_explicit_disallowed_policy_denies_writes(session: Session) -> None:
    """A policy with ``allowed: false`` denies even when scope is held."""
    src = _writeable_source(session, allowed=False, write_modes=["append"])
    identity = make_identity(kind="agent", scopes=frozenset({"sources.write"}))
    assert can_write(identity, src, WriteMode.APPEND) is False


def test_allowed_policy_with_scope_and_mode_permits_write(session: Session) -> None:
    """All gates passing => write allowed."""
    src = _writeable_source(session, write_modes=["append", "annotate"])
    identity = make_identity(kind="agent", scopes=frozenset({"sources.write"}))
    assert can_write(identity, src, WriteMode.APPEND) is True
    assert can_write(identity, src, WriteMode.ANNOTATE) is True


def test_wrong_mode_denied(session: Session) -> None:
    """Caller asks for a mode not listed in the policy => denied."""
    src = _writeable_source(session, write_modes=["append"])
    identity = make_identity(kind="agent", scopes=frozenset({"sources.write"}))
    assert can_write(identity, src, WriteMode.UPSERT) is False


def test_missing_scope_denied(session: Session) -> None:
    """Caller does not hold the required scope => denied."""
    src = _writeable_source(session, write_modes=["append"])
    identity = make_identity(kind="agent", scopes=frozenset())  # no scopes
    assert can_write(identity, src, WriteMode.APPEND) is False


def test_custom_scope_required_enforced(session: Session) -> None:
    """A source can require a custom scope; identities without it are denied."""
    src = _writeable_source(
        session, write_modes=["append"], scope_required="clinical.write"
    )
    has_default = make_identity(kind="agent", scopes=frozenset({"sources.write"}))
    has_custom = make_identity(kind="agent", scopes=frozenset({"clinical.write"}))
    assert can_write(has_default, src, WriteMode.APPEND) is False
    assert can_write(has_custom, src, WriteMode.APPEND) is True


def test_allowed_groups_intersection_required(session: Session) -> None:
    """If allowed_groups is set, the caller's groups must intersect."""
    src = _writeable_source(
        session,
        write_modes=["append"],
        allowed_groups=["clinical-agents"],
    )
    matching = make_identity(
        kind="agent",
        groups=("clinical-agents",),
        scopes=frozenset({"sources.write"}),
    )
    not_matching = make_identity(
        kind="agent",
        groups=("research-agents",),
        scopes=frozenset({"sources.write"}),
    )
    assert can_write(matching, src, WriteMode.APPEND) is True
    assert can_write(not_matching, src, WriteMode.APPEND) is False


def test_empty_allowed_groups_means_anyone_with_scope(session: Session) -> None:
    """allowed_groups == [] means 'any caller with the scope' per catalog.md."""
    src = _writeable_source(session, write_modes=["append"], allowed_groups=[])
    identity = make_identity(kind="agent", scopes=frozenset({"sources.write"}))
    assert can_write(identity, src, WriteMode.APPEND) is True


def test_writes_denied_against_draft_source(session: Session) -> None:
    """A Draft source rejects writes regardless of policy."""
    src = _writeable_source(
        session,
        write_modes=["append"],
        status=SourceStatus.DRAFT,
    )
    identity = make_identity(kind="agent", scopes=frozenset({"sources.write"}))
    assert can_write(identity, src, WriteMode.APPEND) is False


def test_writes_denied_against_retired_source(session: Session) -> None:
    """A Retired source rejects writes regardless of policy."""
    src = _writeable_source(
        session,
        write_modes=["append"],
        status=SourceStatus.RETIRED,
    )
    identity = make_identity(kind="agent", scopes=frozenset({"sources.write"}))
    assert can_write(identity, src, WriteMode.APPEND) is False
