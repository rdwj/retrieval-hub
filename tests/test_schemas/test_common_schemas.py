"""Tests for shared schema fragments and reserved error codes."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from retrieval_hub.schemas.common import (
    AccessPolicy,
    AgentWritePolicy,
    ErrorCode,
    Lineage,
    LineageOrigin,
    LineageRefresh,
    OwnerInfo,
)


def test_error_code_values() -> None:
    """The reserved error codes are exhaustively named."""
    assert ErrorCode.SOURCE_NOT_FOUND.value == "SOURCE_NOT_FOUND"
    assert ErrorCode.PUBLISH_REQUIREMENTS_NOT_MET.value == "PUBLISH_REQUIREMENTS_NOT_MET"
    assert "WRITE_DENIED" in {e.value for e in ErrorCode}


def test_owner_info_defaults() -> None:
    """OwnerInfo defaults to empty contacts/maintainers."""
    info = OwnerInfo(team="platform-docs")
    assert info.contacts == []
    assert info.maintainers == []


def test_lineage_nested_construction() -> None:
    """Lineage composes origin and refresh correctly."""
    lineage = Lineage(
        origin=LineageOrigin(kind="web_crawl", config={"roots": ["https://docs.redhat.com"]}),
        refresh=LineageRefresh(cadence="weekly"),
    )
    assert lineage.origin is not None
    assert lineage.origin.kind == "web_crawl"
    assert lineage.refresh is not None
    assert lineage.refresh.cadence == "weekly"


def test_access_policy_extra_field_rejected() -> None:
    """AccessPolicy uses extra=forbid; unknown fields raise ValidationError."""
    with pytest.raises(ValidationError):
        AccessPolicy.model_validate({"visibility": "public", "wat": True})


def test_agent_write_policy_extra_field_rejected() -> None:
    """AgentWritePolicy uses extra=forbid; unknown fields raise ValidationError."""
    with pytest.raises(ValidationError):
        AgentWritePolicy.model_validate({"allowed": True, "extra_thing": 1})
