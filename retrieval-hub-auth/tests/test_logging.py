"""Tests for the redacting logging filter."""

from __future__ import annotations

import logging

from retrieval_hub_auth.logging import (
    REDACTED,
    RedactingFilter,
    configure_logging,
    redact_mapping,
)


def test_redacting_filter_scrubs_jwt_in_message() -> None:
    record = logging.LogRecord(
        name="test",
        level=logging.INFO,
        pathname="x",
        lineno=1,
        msg="Token: eyJhbGciOiJSUzI1NiJ9.eyJzdWIiOiJmb28ifQ.somesig",
        args=(),
        exc_info=None,
    )
    RedactingFilter().filter(record)
    assert REDACTED in record.getMessage()


def test_redacting_filter_scrubs_kv_pairs() -> None:
    record = logging.LogRecord(
        name="test",
        level=logging.INFO,
        pathname="x",
        lineno=1,
        msg="attempt client_secret=supersecret for op",
        args=(),
        exc_info=None,
    )
    RedactingFilter().filter(record)
    assert "supersecret" not in record.getMessage()
    assert REDACTED in record.getMessage()


def test_redacting_filter_scrubs_structured_extras() -> None:
    record = logging.LogRecord(
        name="test",
        level=logging.INFO,
        pathname="x",
        lineno=1,
        msg="context",
        args=(),
        exc_info=None,
    )
    record.__dict__["client_secret"] = "leaked"
    RedactingFilter().filter(record)
    assert record.__dict__["client_secret"] == REDACTED


def test_redact_mapping_helper() -> None:
    redacted = redact_mapping({"client_id": "ok", "client_secret": "bad"})
    assert redacted["client_id"] == "ok"
    assert redacted["client_secret"] == REDACTED


def test_configure_logging_is_idempotent() -> None:
    configure_logging("DEBUG")
    configure_logging("DEBUG")  # second call is a no-op
    root = logging.getLogger()
    filters_on_first_handler = [
        f for f in root.handlers[0].filters if isinstance(f, RedactingFilter)
    ]
    assert len(filters_on_first_handler) == 1
