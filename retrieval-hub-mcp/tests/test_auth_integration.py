"""Tests for auth integration in the RetrievalHub MCP server.

Validates that:
- When auth is disabled (no JWKS URI), tools work without tokens.
- When auth is enabled, access control is enforced via the policy module.
- list_sources filters restricted sources the caller cannot see.
- describe_source / retrieve / refine deny access to restricted sources.
- request_access returns structured guidance.
- get_current_identity() correctly maps AccessToken claims to Identity.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from fastmcp.exceptions import ToolError
from fastmcp.server.auth.auth import AccessToken
from retrieval_hub_mcp.auth import get_current_identity
from retrieval_hub_mcp.server import (
    _parse_source_slugs,
    describe_source,
    list_sources,
    refine,
    request_access,
    retrieve,
)

from retrieval_hub.models.identity import Identity

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_source(
    slug="test-source",
    name="Test Source",
    family="document",
    status="published",
    description_short="A test source",
    description_long="Longer description",
    owner_team="platform",
    active_physical_index_id="pi-001",
    recipe_version_id="rv-001",
    id="src-001",
    usage_rules=None,
    rewriter_metadata=None,
    semantic_context=None,
    access=None,
    visibility="public",
    owner_info=None,
):
    return SimpleNamespace(
        id=id,
        slug=slug,
        name=name,
        family=family,
        status=status,
        description_short=description_short,
        description_long=description_long,
        owner_team=owner_team,
        active_physical_index_id=active_physical_index_id,
        recipe_version_id=recipe_version_id,
        usage_rules=usage_rules,
        rewriter_metadata=rewriter_metadata,
        semantic_context=semantic_context,
        access=access,
        visibility=visibility,
        owner_info=owner_info,
    )


def _make_physical_index(id="pi-001", document_count=42, build_metadata=None):
    return SimpleNamespace(
        id=id,
        document_count=document_count,
        build_metadata=build_metadata,
        recipe_version_id="rv-001",
    )


def _agent_identity(groups=(), scopes=("sources.read",)):
    return Identity(
        sub="agent:test-agent",
        kind="agent",
        groups=tuple(groups),
        scopes=frozenset(scopes),
    )


def _admin_identity():
    return Identity(
        sub="user:admin-user",
        kind="user",
        groups=("admin",),
        scopes=frozenset(("sources.read", "admin.write")),
    )


class _MockQuery:
    """Chainable mock that mimics SQLAlchemy's Query interface."""

    def __init__(self, results):
        self._results = results

    def filter(self, *args, **kwargs):
        return self

    def one_or_none(self):
        if isinstance(self._results, list):
            return self._results[0] if self._results else None
        return self._results

    def all(self):
        if isinstance(self._results, list):
            return self._results
        return [self._results] if self._results else []


# ---------------------------------------------------------------------------
# Auth disabled (backward compatibility)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@patch("retrieval_hub_mcp.server.get_current_identity", return_value=None)
async def test_list_sources_no_auth_returns_all(mock_identity):
    """When auth is disabled, list_sources returns all sources without filtering."""
    source = _make_source()
    pi = _make_physical_index()

    session = MagicMock()
    call_count = 0

    def mock_query(model):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return _MockQuery([source])
        return _MockQuery(pi)

    session.query.side_effect = mock_query

    results = await list_sources(session=session)
    assert len(results) == 1
    assert results[0].slug == "test-source"


@pytest.mark.asyncio
@patch("retrieval_hub_mcp.server.get_current_identity", return_value=None)
async def test_describe_source_no_auth(mock_identity):
    """When auth is disabled, describe_source works without access checks."""
    source = _make_source(active_physical_index_id=None)

    session = MagicMock()
    call_count = 0

    def mock_query(model):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return _MockQuery(source)
        return _MockQuery([])

    session.query.side_effect = mock_query

    result = await describe_source(slug="test-source", session=session)
    assert result.slug == "test-source"


# ---------------------------------------------------------------------------
# list_sources access filtering
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@patch("retrieval_hub_mcp.server.get_current_identity")
async def test_list_sources_filters_restricted_sources(mock_identity):
    """Restricted sources the caller cannot access are omitted from list_sources."""
    mock_identity.return_value = _agent_identity(groups=("allowed-group",))

    public_source = _make_source(slug="public-source")
    restricted_ok = _make_source(
        slug="restricted-ok",
        access={"visibility": "restricted", "allowed_groups": ["allowed-group"]},
        visibility="restricted",
    )
    restricted_denied = _make_source(
        slug="restricted-denied",
        access={"visibility": "restricted", "allowed_groups": ["other-group"]},
        visibility="restricted",
    )
    pi = _make_physical_index()

    session = MagicMock()
    call_count = 0

    def mock_query(model):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return _MockQuery([public_source, restricted_ok, restricted_denied])
        return _MockQuery(pi)

    session.query.side_effect = mock_query

    results = await list_sources(session=session)
    slugs = [r.slug for r in results]
    assert "public-source" in slugs
    assert "restricted-ok" in slugs
    assert "restricted-denied" not in slugs


@pytest.mark.asyncio
@patch("retrieval_hub_mcp.server.get_current_identity")
async def test_list_sources_admin_sees_all(mock_identity):
    """Admin users bypass restricted visibility checks."""
    mock_identity.return_value = _admin_identity()

    restricted = _make_source(
        slug="restricted-source",
        access={"visibility": "restricted", "allowed_groups": ["special"]},
        visibility="restricted",
    )
    pi = _make_physical_index()

    session = MagicMock()
    call_count = 0

    def mock_query(model):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return _MockQuery([restricted])
        return _MockQuery(pi)

    session.query.side_effect = mock_query

    results = await list_sources(session=session)
    assert len(results) == 1
    assert results[0].slug == "restricted-source"


# ---------------------------------------------------------------------------
# describe_source access control
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@patch("retrieval_hub_mcp.server.get_current_identity")
async def test_describe_source_denied_for_restricted_source(mock_identity):
    """describe_source raises ToolError when caller lacks access."""
    mock_identity.return_value = _agent_identity(groups=())

    source = _make_source(
        slug="restricted-source",
        access={"visibility": "restricted", "allowed_groups": ["special-team"]},
        visibility="restricted",
    )

    session = MagicMock()
    session.query.return_value = _MockQuery(source)

    with pytest.raises(ToolError, match="Access denied"):
        await describe_source(slug="restricted-source", session=session)


@pytest.mark.asyncio
@patch("retrieval_hub_mcp.server.get_current_identity")
async def test_describe_source_allowed_with_correct_group(mock_identity):
    """describe_source succeeds when caller's group matches allowed_groups."""
    mock_identity.return_value = _agent_identity(groups=("special-team",))

    source = _make_source(
        slug="restricted-source",
        active_physical_index_id=None,
        access={"visibility": "restricted", "allowed_groups": ["special-team"]},
        visibility="restricted",
    )

    session = MagicMock()
    call_count = 0

    def mock_query(model):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return _MockQuery(source)
        return _MockQuery([])

    session.query.side_effect = mock_query

    result = await describe_source(slug="restricted-source", session=session)
    assert result.slug == "restricted-source"


# ---------------------------------------------------------------------------
# retrieve access control
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@patch("retrieval_hub_mcp.server.get_current_identity")
@patch("retrieval_hub_mcp.server.retrieval_query")
async def test_retrieve_denied_for_restricted_source(mock_query_fn, mock_identity):
    """retrieve raises ToolError when caller lacks access to the source."""
    mock_identity.return_value = _agent_identity(groups=())

    source = _make_source(
        slug="restricted-source",
        access={"visibility": "restricted", "allowed_groups": ["team-a"]},
        visibility="restricted",
    )

    session = MagicMock()
    session.query.return_value = _MockQuery(source)

    with pytest.raises(ToolError, match="Access denied"):
        await retrieve(
            query="test query",
            source="restricted-source",
            session=session,
        )


@pytest.mark.asyncio
@patch("retrieval_hub_mcp.server.get_current_identity")
@patch("retrieval_hub_mcp.server.retrieval_query")
async def test_retrieve_succeeds_with_correct_group(mock_query_fn, mock_identity):
    """retrieve succeeds when caller has the right group."""
    mock_identity.return_value = _agent_identity(groups=("team-a",))

    result = SimpleNamespace(
        chunk_id="c1",
        text="passage",
        score=0.9,
        doc_title="Doc",
        doc_url="https://example.com",
        doc_section="Sec",
        chunk_index=0,
        request_id="req-1",
    )
    mock_query_fn.return_value = [result]

    source = _make_source(
        slug="restricted-source",
        active_physical_index_id=None,
        access={"visibility": "restricted", "allowed_groups": ["team-a"]},
        visibility="restricted",
    )

    session = MagicMock()
    session.query.return_value = _MockQuery(source)

    response = await retrieve(
        query="test query",
        source="restricted-source",
        session=session,
    )
    assert len(response.hits) == 1


# ---------------------------------------------------------------------------
# refine access control
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@patch("retrieval_hub_mcp.server.get_current_identity")
async def test_refine_denied_for_restricted_source(mock_identity):
    """refine raises ToolError when caller lacks access."""
    mock_identity.return_value = _agent_identity(groups=())

    source = _make_source(
        slug="restricted-source",
        access={"visibility": "restricted", "allowed_groups": ["team-b"]},
        visibility="restricted",
    )

    session = MagicMock()
    session.query.return_value = _MockQuery(source)

    with pytest.raises(ToolError, match="Access denied"):
        await refine(
            source="restricted-source",
            doc_title="Doc",
            chunk_index=0,
            query="expand context",
            session=session,
        )


# ---------------------------------------------------------------------------
# request_access tool
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_request_access_public_source():
    """request_access on a public source returns a 'no special access needed' message."""
    source = _make_source(slug="public-source", access={"visibility": "public"})

    session = MagicMock()
    session.query.return_value = _MockQuery(source)

    result = await request_access(slug="public-source", session=session)
    assert result["visibility"] == "public"
    assert "no special access" in result["message"].lower()


@pytest.mark.asyncio
async def test_request_access_restricted_source():
    """request_access on a restricted source returns groups, owner, and contacts."""
    source = _make_source(
        slug="restricted-source",
        owner_team="clinical-standards",
        access={
            "visibility": "restricted",
            "allowed_groups": ["cardiology-team"],
        },
        owner_info={"contacts": ["jane@example.com"]},
    )

    session = MagicMock()
    session.query.return_value = _MockQuery(source)

    result = await request_access(slug="restricted-source", session=session)
    assert result["visibility"] == "restricted"
    assert result["required_groups"] == ["cardiology-team"]
    assert result["owner_team"] == "clinical-standards"
    assert result["contacts"] == ["jane@example.com"]
    assert "guidance" in result


@pytest.mark.asyncio
async def test_request_access_source_not_found():
    """request_access raises ToolError for unknown slugs."""
    session = MagicMock()
    session.query.return_value = _MockQuery(None)

    with pytest.raises(ToolError, match="No source"):
        await request_access(slug="nonexistent", session=session)


# ---------------------------------------------------------------------------
# Draft/Retired lifecycle gate
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@patch("retrieval_hub_mcp.server.get_current_identity")
async def test_list_sources_agent_cannot_see_draft(mock_identity):
    """Agent-kind identities cannot see draft sources."""
    mock_identity.return_value = _agent_identity()

    draft_source = _make_source(slug="draft-src", status="draft")

    session = MagicMock()
    session.query.return_value = _MockQuery([draft_source])

    results = await list_sources(session=session)
    assert len(results) == 0


# ---------------------------------------------------------------------------
# Wildcard and multi-source access filtering
# ---------------------------------------------------------------------------


def test_parse_source_slugs_star_filters_by_identity():
    """Wildcard '*' filters sources the caller cannot access."""
    identity = _agent_identity(groups=("team-a",))

    public = _make_source(slug="public", active_physical_index_id="pi-1")
    restricted_ok = _make_source(
        slug="restricted-ok",
        active_physical_index_id="pi-2",
        access={"visibility": "restricted", "allowed_groups": ["team-a"]},
        visibility="restricted",
    )
    restricted_denied = _make_source(
        slug="restricted-denied",
        active_physical_index_id="pi-3",
        access={"visibility": "restricted", "allowed_groups": ["team-b"]},
        visibility="restricted",
    )

    session = MagicMock()
    session.query.return_value = _MockQuery([public, restricted_ok, restricted_denied])

    slugs = _parse_source_slugs("*", session, identity)
    assert "public" in slugs
    assert "restricted-ok" in slugs
    assert "restricted-denied" not in slugs


def test_parse_source_slugs_star_no_identity_returns_all():
    """Wildcard '*' without identity returns all sources (auth disabled)."""
    src = _make_source(slug="any-source", active_physical_index_id="pi-1")

    session = MagicMock()
    session.query.return_value = _MockQuery([src])

    slugs = _parse_source_slugs("*", session, identity=None)
    assert slugs == ["any-source"]


@pytest.mark.asyncio
@patch("retrieval_hub_mcp.server.get_current_identity")
@patch("retrieval_hub_mcp.server.retrieval_multi_query")
@patch("retrieval_hub_mcp.server.rrf_merge")
async def test_retrieve_multi_source_denies_restricted(
    mock_rrf, mock_multi_query, mock_identity,
):
    """retrieve with comma-separated slugs raises ToolError on restricted source."""
    mock_identity.return_value = _agent_identity(groups=())

    public_src = _make_source(slug="public-src")
    restricted_src = _make_source(
        slug="restricted-src",
        access={"visibility": "restricted", "allowed_groups": ["team-x"]},
        visibility="restricted",
    )

    session = MagicMock()
    call_count = 0

    def mock_query(model):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return _MockQuery(public_src)
        return _MockQuery(restricted_src)

    session.query.side_effect = mock_query

    with pytest.raises(ToolError, match="Access denied"):
        await retrieve(
            query="test",
            source="public-src,restricted-src",
            session=session,
        )


# ---------------------------------------------------------------------------
# refine success with correct group
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@patch("retrieval_hub_mcp.server.get_current_identity")
@patch("retrieval_hub_mcp.server.retrieval_refine")
async def test_refine_succeeds_with_correct_group(mock_refine_fn, mock_identity):
    """refine succeeds when caller has the right group for a restricted source."""
    mock_identity.return_value = _agent_identity(groups=("team-b",))

    refine_output = SimpleNamespace(
        results=[
            SimpleNamespace(
                chunk_id="c1",
                text="context text",
                doc_section="Section 1",
                chunk_index=0,
                doc_title="Doc",
                doc_url="https://example.com",
            ),
        ],
        truncated=False,
        total_chunks=1,
    )
    mock_refine_fn.return_value = refine_output

    source = _make_source(
        slug="restricted-src",
        active_physical_index_id=None,
        access={"visibility": "restricted", "allowed_groups": ["team-b"]},
        visibility="restricted",
    )

    session = MagicMock()
    session.query.return_value = _MockQuery(source)

    result = await refine(
        source="restricted-src",
        doc_title="Doc",
        chunk_index=0,
        query="expand context",
        session=session,
    )
    assert len(result.chunks) == 1


# ---------------------------------------------------------------------------
# get_current_identity() unit tests
# ---------------------------------------------------------------------------


@patch("retrieval_hub_mcp.auth.get_access_token")
def test_get_current_identity_maps_claims(mock_get_token):
    """get_current_identity extracts rh_* claims into Identity fields."""
    mock_get_token.return_value = AccessToken(
        token="fake-jwt",
        client_id="test-client",
        scopes=["sources.read", "sources.query"],
        subject="agent:test-agent-01",
        claims={
            "sub": "agent:test-agent-01",
            "rh_identity_kind": "agent",
            "rh_identity_groups": ["team-alpha", "team-beta"],
            "rh_tenant": "acme-corp",
            "rh_request_id": "req-123",
        },
    )

    identity = get_current_identity()
    assert identity is not None
    assert identity.sub == "agent:test-agent-01"
    assert identity.kind == "agent"
    assert identity.groups == ("team-alpha", "team-beta")
    assert identity.scopes == frozenset({"sources.read", "sources.query"})
    assert identity.tenant == "acme-corp"
    assert identity.request_id == "req-123"


@patch("retrieval_hub_mcp.auth.get_access_token")
def test_get_current_identity_returns_none_without_token(mock_get_token):
    """get_current_identity returns None when no access token is present."""
    mock_get_token.return_value = None
    assert get_current_identity() is None


@patch("retrieval_hub_mcp.auth.get_access_token")
def test_get_current_identity_defaults(mock_get_token):
    """get_current_identity uses sensible defaults for missing claims."""
    mock_get_token.return_value = AccessToken(
        token="minimal-jwt",
        client_id="minimal-client",
        scopes=[],
        subject="svc:minimal",
        claims={"sub": "svc:minimal"},
    )

    identity = get_current_identity()
    assert identity is not None
    assert identity.kind == "agent"
    assert identity.groups == ()
    assert identity.tenant == "default"
    assert identity.request_id is None


# ---------------------------------------------------------------------------
# Google OAuth identity extraction
# ---------------------------------------------------------------------------


@patch("retrieval_hub_mcp.auth.get_access_token")
def test_google_token_extracts_identity(mock_get_token):
    """Google OAuth token produces a user Identity with email."""
    mock_get_token.return_value = AccessToken(
        token="google-opaque-token",
        client_id="google-client",
        scopes=["openid", "email", "profile"],
        subject="112233445566",
        claims={
            "sub": "112233445566",
            "email": "alice@redhat.com",
            "email_verified": True,
            "name": "Alice Smith",
        },
    )

    identity = get_current_identity()
    assert identity is not None
    assert identity.sub == "google:112233445566"
    assert identity.kind == "user"
    assert identity.email == "alice@redhat.com"
    assert identity.email_domain == "redhat.com"
    assert identity.groups == ()
    assert "openid" in identity.scopes


@patch("retrieval_hub_mcp.auth.get_access_token")
def test_google_token_rejects_non_redhat_domain(mock_get_token):
    """Google OAuth rejects emails not from @redhat.com."""
    mock_get_token.return_value = AccessToken(
        token="google-opaque-token",
        client_id="google-client",
        scopes=["openid", "email"],
        subject="999",
        claims={
            "sub": "999",
            "email": "user@gmail.com",
            "email_verified": True,
        },
    )

    with pytest.raises(PermissionError, match="@redhat.com"):
        get_current_identity()


@patch("retrieval_hub_mcp.auth.get_access_token")
def test_google_token_rejects_unverified_email(mock_get_token):
    """Google OAuth rejects unverified email addresses."""
    mock_get_token.return_value = AccessToken(
        token="google-opaque-token",
        client_id="google-client",
        scopes=["openid", "email"],
        subject="888",
        claims={
            "sub": "888",
            "email": "alice@redhat.com",
            "email_verified": False,
        },
    )

    with pytest.raises(PermissionError, match="not verified"):
        get_current_identity()


@patch("retrieval_hub_mcp.auth.get_access_token")
def test_jwt_token_still_works_with_google_support(mock_get_token):
    """JWT tokens with rh_identity_kind still go through the JWT path."""
    mock_get_token.return_value = AccessToken(
        token="jwt-token",
        client_id="my-agent",
        scopes=["sources.read"],
        subject="agent:my-agent",
        claims={
            "sub": "agent:my-agent",
            "rh_identity_kind": "agent",
            "rh_identity_groups": ["team-x"],
            "rh_tenant": "acme",
        },
    )

    identity = get_current_identity()
    assert identity is not None
    assert identity.sub == "agent:my-agent"
    assert identity.kind == "agent"
    assert identity.groups == ("team-x",)
    assert identity.tenant == "acme"
    assert identity.email is None
