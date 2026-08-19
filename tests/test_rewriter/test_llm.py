"""Tests for the async LLM client (httpx-based, OpenAI-compatible)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

from retrieval_hub.rewriter.llm import LlmClient, LlmError, _normalize_base_url

# ---------------------------------------------------------------------------
# URL normalisation (pure function, no I/O)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("https://llm.example.com", "https://llm.example.com"),
        ("https://llm.example.com/", "https://llm.example.com"),
        ("https://llm.example.com/v1", "https://llm.example.com"),
        ("https://llm.example.com/v1/", "https://llm.example.com"),
        (
            "https://llm.example.com/v1/chat/completions",
            "https://llm.example.com",
        ),
        (
            "https://llm.example.com/v1/chat/completions/",
            "https://llm.example.com",
        ),
        (
            "https://llm.example.com/chat/completions",
            "https://llm.example.com",
        ),
        ("http://localhost:8000", "http://localhost:8000"),
        ("http://localhost:8000/v1", "http://localhost:8000"),
    ],
    ids=[
        "bare-host",
        "trailing-slash",
        "trailing-v1",
        "trailing-v1-slash",
        "full-openai-path",
        "full-openai-path-slash",
        "chat-completions-only",
        "localhost-bare",
        "localhost-v1",
    ],
)
def test_normalize_base_url(raw: str, expected: str) -> None:
    assert _normalize_base_url(raw) == expected


# ---------------------------------------------------------------------------
# LlmClient property
# ---------------------------------------------------------------------------


def test_model_property() -> None:
    client = LlmClient("https://example.com", model="granite-3.3-8b")
    assert client.model == "granite-3.3-8b"


# ---------------------------------------------------------------------------
# Helpers for mocking httpx
# ---------------------------------------------------------------------------


def _ok_response(content: str = "test content") -> MagicMock:
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = {
        "choices": [{"message": {"content": content}}],
    }
    resp.raise_for_status = MagicMock()
    return resp


# ---------------------------------------------------------------------------
# chat() happy path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_chat_returns_assistant_content() -> None:
    client = LlmClient("https://example.com/v1", model="test-model")
    client._client.post = AsyncMock(return_value=_ok_response("hello world"))

    result = await client.chat([{"role": "user", "content": "hi"}])

    assert result == "hello world"
    call_kwargs = client._client.post.call_args
    assert "/v1/chat/completions" in call_kwargs.args[0]
    payload = call_kwargs.kwargs["json"]
    assert payload["model"] == "test-model"
    assert payload["temperature"] == 0.0


@pytest.mark.asyncio
async def test_chat_sends_custom_temperature_and_max_tokens() -> None:
    client = LlmClient("https://example.com", model="m")
    client._client.post = AsyncMock(return_value=_ok_response())

    await client.chat(
        [{"role": "user", "content": "q"}],
        temperature=0.7,
        max_tokens=512,
    )

    payload = client._client.post.call_args.kwargs["json"]
    assert payload["temperature"] == 0.7
    assert payload["max_tokens"] == 512


# ---------------------------------------------------------------------------
# chat() error paths
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_chat_raises_on_http_error() -> None:
    client = LlmClient("https://example.com", model="m")
    error_resp = MagicMock()
    error_resp.status_code = 500
    error_resp.text = "Internal Server Error"
    error_resp.raise_for_status.side_effect = httpx.HTTPStatusError(
        "Server Error",
        request=MagicMock(),
        response=error_resp,
    )
    client._client.post = AsyncMock(return_value=error_resp)

    with pytest.raises(LlmError, match="HTTP 500"):
        await client.chat([{"role": "user", "content": "q"}])


@pytest.mark.asyncio
async def test_chat_raises_on_connection_error() -> None:
    client = LlmClient("https://example.com", model="m")
    client._client.post = AsyncMock(
        side_effect=httpx.ConnectError("Connection refused")
    )

    with pytest.raises(LlmError, match="request failed"):
        await client.chat([{"role": "user", "content": "q"}])


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("bad_body", "desc"),
    [
        ({}, "missing-choices"),
        ({"choices": []}, "empty-choices"),
        ({"choices": [{}]}, "missing-message"),
        ({"choices": [{"message": {}}]}, "missing-content"),
    ],
    ids=["missing-choices", "empty-choices", "missing-message", "missing-content"],
)
async def test_chat_raises_on_malformed_response(
    bad_body: dict, desc: str
) -> None:
    client = LlmClient("https://example.com", model="m")
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = bad_body
    resp.text = str(bad_body)
    resp.raise_for_status = MagicMock()
    client._client.post = AsyncMock(return_value=resp)

    with pytest.raises(LlmError, match="Unexpected LLM response"):
        await client.chat([{"role": "user", "content": "q"}])


# ---------------------------------------------------------------------------
# Context-manager support
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_context_manager_calls_close() -> None:
    client = LlmClient("https://example.com", model="m")
    client._client = MagicMock()
    client._client.aclose = AsyncMock()

    async with client as ctx:
        assert ctx is client

    client._client.aclose.assert_awaited_once()
