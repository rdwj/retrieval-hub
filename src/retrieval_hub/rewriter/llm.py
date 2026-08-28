"""Async LLM client for OpenAI-compatible chat-completion endpoints."""

from __future__ import annotations

import logging
from types import TracebackType

import httpx

logger = logging.getLogger(__name__)


class LlmError(Exception):
    """Raised when an LLM call fails (HTTP error, malformed response, etc.)."""


def _normalize_base_url(url: str) -> str:
    """Strip trailing slash and ``/chat/completions`` or ``/v1/chat/completions``."""
    url = url.rstrip("/")
    for suffix in ("/chat/completions", "/v1/chat/completions", "/v1"):
        if url.endswith(suffix):
            url = url[: -len(suffix)]
    return url


class LlmClient:
    """Thin async wrapper around an OpenAI-compatible chat-completions endpoint.

    Parameters
    ----------
    base_url:
        The root URL of the model server.  Trailing ``/v1/chat/completions``
        is stripped so callers can pass either the bare host or the full path.
    model:
        Model identifier sent in the request body.
    timeout:
        HTTP timeout in seconds.
    """

    def __init__(
        self,
        base_url: str,
        model: str = "/mnt/models",
        timeout: float = 120.0,
    ) -> None:
        self._base_url = _normalize_base_url(base_url)
        self._model = model
        self._client = httpx.AsyncClient(timeout=timeout)

    @property
    def model(self) -> str:
        return self._model

    async def chat(
        self,
        messages: list[dict[str, str]],
        *,
        temperature: float = 0.0,
        max_tokens: int = 2048,
    ) -> str:
        """Send a chat-completion request and return the assistant content."""
        url = f"{self._base_url}/v1/chat/completions"
        payload = {
            "model": self._model,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        logger.debug("llm.chat url=%s model=%s messages=%d", url, self._model, len(messages))

        try:
            resp = await self._client.post(url, json=payload)
            resp.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise LlmError(
                f"LLM returned HTTP {exc.response.status_code}: "
                f"{exc.response.text[:500]}"
            ) from exc
        except httpx.HTTPError as exc:
            raise LlmError(f"LLM request failed: {exc}") from exc

        try:
            data = resp.json()
            content: str | None = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, ValueError) as exc:
            raise LlmError(
                f"Unexpected LLM response structure: {resp.text[:500]}"
            ) from exc

        if content is None:
            content = ""
        logger.debug("llm.chat response_length=%d", len(content))
        return content

    async def close(self) -> None:
        """Close the underlying HTTP client."""
        await self._client.aclose()

    async def __aenter__(self) -> LlmClient:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        await self.close()
