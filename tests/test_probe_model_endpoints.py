"""Tests for the model endpoint health probe."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import httpx
from scripts.probe_model_endpoints import probe_endpoint


def test_probe_endpoint_healthy() -> None:
    """Healthy endpoint returns status healthy with latency."""
    mock_resp = MagicMock(status_code=200)
    with patch("httpx.get", return_value=mock_resp):
        status, latency, error = probe_endpoint("http://test:8000")
    assert status == "healthy"
    assert latency is not None
    assert latency > 0
    assert error is None


def test_probe_endpoint_server_error() -> None:
    """Non-2xx status returns unhealthy with HTTP status in error."""
    mock_resp = MagicMock(status_code=503)
    with patch("httpx.get", return_value=mock_resp):
        status, latency, error = probe_endpoint("http://test:8000")
    assert status == "unhealthy"
    assert latency is not None
    assert error is not None
    assert "503" in error


def test_probe_endpoint_timeout() -> None:
    """Timeout returns unhealthy with Timeout error."""
    with patch("httpx.get", side_effect=httpx.TimeoutException("timeout")):
        status, latency, error = probe_endpoint("http://test:8000")
    assert status == "unhealthy"
    assert latency is None
    assert error == "Timeout"


def test_probe_endpoint_connection_error() -> None:
    """Connection error returns unhealthy with error message."""
    with patch("httpx.get", side_effect=httpx.ConnectError("Connection refused")):
        status, latency, error = probe_endpoint("http://test:8000")
    assert status == "unhealthy"
    assert latency is None
    assert error is not None
    assert "refused" in error.lower()


def test_probe_endpoint_passes_timeout_to_httpx() -> None:
    """Custom timeout is forwarded to httpx.get."""
    mock_resp = MagicMock(status_code=200)
    with patch("httpx.get", return_value=mock_resp) as mock_get:
        probe_endpoint("http://test:8000", timeout=15.0)
    mock_get.assert_called_once_with("http://test:8000/health", timeout=15.0)


def test_probe_endpoint_appends_health_path() -> None:
    """Probe URL is endpoint_url + /health."""
    mock_resp = MagicMock(status_code=200)
    with patch("httpx.get", return_value=mock_resp) as mock_get:
        probe_endpoint("http://model-server:9000")
    mock_get.assert_called_once_with("http://model-server:9000/health", timeout=5.0)


def test_probe_endpoint_unexpected_exception() -> None:
    """Unexpected exceptions are caught and reported as unhealthy."""
    with patch("httpx.get", side_effect=RuntimeError("unexpected")):
        status, latency, error = probe_endpoint("http://test:8000")
    assert status == "unhealthy"
    assert latency is None
    assert error is not None
    assert "unexpected" in error


def test_probe_endpoint_client_error_status() -> None:
    """4xx responses are treated as unhealthy."""
    mock_resp = MagicMock(status_code=404)
    with patch("httpx.get", return_value=mock_resp):
        status, latency, error = probe_endpoint("http://test:8000")
    assert status == "unhealthy"
    assert "404" in error  # type: ignore[operator]


def test_probe_endpoint_redirect_is_healthy() -> None:
    """3xx responses (< 400) are treated as healthy."""
    mock_resp = MagicMock(status_code=301)
    with patch("httpx.get", return_value=mock_resp):
        status, latency, error = probe_endpoint("http://test:8000")
    assert status == "healthy"
    assert error is None
