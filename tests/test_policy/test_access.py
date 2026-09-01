"""Tests for ``policy.access.can_access``.

These mirror the pseudocode in docs/auth.md exactly. Every test names a
specific scenario from that document.
"""

from __future__ import annotations

import pytest
from sqlalchemy.orm import Session

from retrieval_hub.models.enums import (
    AccessVisibility,
    SourceStatus,
)
from retrieval_hub.policy import can_access
from tests.conftest import make_identity, make_source


@pytest.mark.parametrize("action", ["list", "read", "query", "rewrite"])
def test_public_source_visible_to_any_authenticated_agent(
    session: Session, action: str
) -> None:
    """A public source allows every read-side action to any authenticated identity."""
    src = make_source(
        session,
        status=SourceStatus.PUBLISHED,
        visibility=AccessVisibility.PUBLIC,
    )
    identity = make_identity(kind="agent")
    assert can_access(identity, src, action) is True  # type: ignore[arg-type]


def test_restricted_source_with_intersecting_groups_allowed(session: Session) -> None:
    """A restricted source allows callers whose groups intersect allowed_groups."""
    src = make_source(
        session,
        status=SourceStatus.PUBLISHED,
        visibility=AccessVisibility.RESTRICTED,
        access={
            "visibility": "restricted",
            "allowed_groups": ["clinical-agents", "platform-admins"],
        },
    )
    identity = make_identity(kind="agent", groups=("clinical-agents",))
    assert can_access(identity, src, "query") is True


def test_restricted_source_without_intersecting_groups_denied(session: Session) -> None:
    """A restricted source denies callers whose groups do not intersect."""
    src = make_source(
        session,
        status=SourceStatus.PUBLISHED,
        visibility=AccessVisibility.RESTRICTED,
        access={"visibility": "restricted", "allowed_groups": ["clinical-agents"]},
    )
    identity = make_identity(kind="agent", groups=("research-agents",))
    assert can_access(identity, src, "query") is False


def test_restricted_source_with_no_allowed_groups_denied(session: Session) -> None:
    """A restricted source with empty allowed_groups denies non-admin agents."""
    src = make_source(
        session,
        status=SourceStatus.PUBLISHED,
        visibility=AccessVisibility.RESTRICTED,
        access={"visibility": "restricted", "allowed_groups": []},
    )
    identity = make_identity(kind="agent", groups=("clinical-agents",))
    assert can_access(identity, src, "read") is False


def test_admin_user_bypasses_restricted_visibility(session: Session) -> None:
    """A human user in the 'admin' group bypasses restricted visibility checks."""
    src = make_source(
        session,
        status=SourceStatus.PUBLISHED,
        visibility=AccessVisibility.RESTRICTED,
        access={"visibility": "restricted", "allowed_groups": ["clinical-agents"]},
    )
    admin = make_identity(sub="user:alice", kind="user", groups=("admin",))
    assert can_access(admin, src, "read") is True


def test_admin_kind_agent_does_not_bypass(session: Session) -> None:
    """An *agent* with an 'admin' group does NOT bypass restricted visibility."""
    src = make_source(
        session,
        status=SourceStatus.PUBLISHED,
        visibility=AccessVisibility.RESTRICTED,
        access={"visibility": "restricted", "allowed_groups": ["clinical-agents"]},
    )
    rogue = make_identity(kind="agent", groups=("admin",))
    # No intersection with allowed_groups; admin bypass is humans-only.
    assert can_access(rogue, src, "read") is False


@pytest.mark.parametrize("status", [SourceStatus.DRAFT, SourceStatus.RETIRED])
def test_draft_and_retired_sources_invisible_to_agents(
    session: Session, status: SourceStatus
) -> None:
    """Draft and Retired sources are not visible to agent identities."""
    src = make_source(
        session,
        status=status,
        visibility=AccessVisibility.PUBLIC,
    )
    identity = make_identity(kind="agent")
    assert can_access(identity, src, "query") is False


def test_human_user_can_see_draft(session: Session) -> None:
    """A human user (UI surface) can still see Draft sources for owner views."""
    src = make_source(
        session,
        status=SourceStatus.DRAFT,
        visibility=AccessVisibility.PUBLIC,
    )
    user = make_identity(sub="user:alice", kind="user")
    # Public visibility + non-agent kind => allowed.
    assert can_access(user, src, "read") is True


def test_curated_source_visible_to_agents(session: Session) -> None:
    """Curated sources are visible to agents per the lifecycle rules."""
    src = make_source(
        session,
        status=SourceStatus.CURATED,
        visibility=AccessVisibility.PUBLIC,
    )
    identity = make_identity(kind="agent")
    assert can_access(identity, src, "query") is True


# ---------------------------------------------------------------------------
# Email-based access control
# ---------------------------------------------------------------------------


def test_restricted_source_with_matching_email_allowed(session: Session) -> None:
    """A restricted source allows callers whose email is in allowed_emails."""
    src = make_source(
        session,
        status=SourceStatus.PUBLISHED,
        visibility=AccessVisibility.RESTRICTED,
        access={
            "visibility": "restricted",
            "allowed_emails": ["alice@redhat.com"],
        },
    )
    identity = make_identity(
        sub="google:123", kind="user", email="alice@redhat.com"
    )
    assert can_access(identity, src, "query") is True


def test_restricted_source_with_non_matching_email_denied(session: Session) -> None:
    """A restricted source denies callers whose email is not in allowed_emails."""
    src = make_source(
        session,
        status=SourceStatus.PUBLISHED,
        visibility=AccessVisibility.RESTRICTED,
        access={
            "visibility": "restricted",
            "allowed_emails": ["alice@redhat.com"],
        },
    )
    identity = make_identity(
        sub="google:456", kind="user", email="bob@redhat.com"
    )
    assert can_access(identity, src, "query") is False


def test_restricted_source_email_case_insensitive(session: Session) -> None:
    """Email matching is case-insensitive."""
    src = make_source(
        session,
        status=SourceStatus.PUBLISHED,
        visibility=AccessVisibility.RESTRICTED,
        access={
            "visibility": "restricted",
            "allowed_emails": ["Alice@RedHat.com"],
        },
    )
    identity = make_identity(
        sub="google:123", kind="user", email="ALICE@REDHAT.COM"
    )
    assert can_access(identity, src, "query") is True


def test_restricted_source_email_or_group(session: Session) -> None:
    """Either matching email OR matching group grants access."""
    src = make_source(
        session,
        status=SourceStatus.PUBLISHED,
        visibility=AccessVisibility.RESTRICTED,
        access={
            "visibility": "restricted",
            "allowed_groups": ["team-a"],
            "allowed_emails": ["alice@redhat.com"],
        },
    )
    by_group = make_identity(kind="agent", groups=("team-a",))
    assert can_access(by_group, src, "query") is True

    by_email = make_identity(
        sub="google:123", kind="user", email="alice@redhat.com"
    )
    assert can_access(by_email, src, "query") is True


def test_restricted_source_no_allowed_emails_key(session: Session) -> None:
    """A restricted source without allowed_emails uses only group-based access."""
    src = make_source(
        session,
        status=SourceStatus.PUBLISHED,
        visibility=AccessVisibility.RESTRICTED,
        access={
            "visibility": "restricted",
            "allowed_groups": ["team-a"],
        },
    )
    identity = make_identity(
        sub="google:123", kind="user", email="alice@redhat.com"
    )
    assert can_access(identity, src, "query") is False


def test_machine_identity_denied_for_email_only_restricted(
    session: Session,
) -> None:
    """A machine identity (no email) is denied for a source with only allowed_emails."""
    src = make_source(
        session,
        status=SourceStatus.PUBLISHED,
        visibility=AccessVisibility.RESTRICTED,
        access={
            "visibility": "restricted",
            "allowed_emails": ["alice@redhat.com"],
        },
    )
    identity = make_identity(kind="agent")
    assert can_access(identity, src, "query") is False
