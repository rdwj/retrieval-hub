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
