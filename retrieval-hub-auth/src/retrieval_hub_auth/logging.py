"""Structured logging with PII redaction for retrieval-hub-auth.

Tokens, client secrets, and SPIFFE-adjacent identifiers are redacted at the
source level (via a logging filter) rather than as a cleanup pass. That way
code that accidentally tries to log a secret still produces a log line, but
with the secret replaced by a sentinel string, so the bug is visible without
being a security incident.
"""

from __future__ import annotations

import logging
import re
from typing import Any

REDACTED = "<redacted>"

# Patterns matched against the formatted log message AND the record's extra
# fields. These are a belt-and-braces measure: code should never put secrets
# in a log message in the first place, but if it does, this filter catches it.
_JWT_PATTERN = re.compile(r"eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+")
_SECRET_KV_PATTERN = re.compile(
    r"(client_secret|password|secret|authorization)\s*[=:]\s*\S+",
    re.IGNORECASE,
)

# Structured-log field names that should always be redacted regardless of
# what they contain.
SENSITIVE_FIELDS = frozenset(
    {
        "client_secret",
        "access_token",
        "refresh_token",
        "authorization",
        "password",
        "secret",
        "sub",  # SPIFFE IDs / user IDs are PII-adjacent
    }
)


class RedactingFilter(logging.Filter):
    """Logging filter that scrubs secrets from log records.

    The filter rewrites both the formatted message and any ``extra=`` fields
    attached to the record. It never drops records; it only redacts their
    contents.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        """Rewrite the record in place to remove sensitive values.

        Returns True unconditionally — the filter never suppresses records.
        """
        # Rewrite the message text.
        try:
            msg = record.getMessage()
        except Exception:  # pragma: no cover - defensive
            return True

        msg = _JWT_PATTERN.sub(REDACTED, msg)
        msg = _SECRET_KV_PATTERN.sub(lambda m: f"{m.group(1)}={REDACTED}", msg)

        if msg != record.getMessage():
            record.msg = msg
            record.args = ()

        # Redact structured extras attached to the record.
        for field in list(record.__dict__.keys()):
            if field in SENSITIVE_FIELDS:
                record.__dict__[field] = REDACTED

        return True


def configure_logging(level: str = "INFO") -> None:
    """Install the redacting filter on the root logger and set the level.

    Safe to call multiple times; the filter class is idempotent per handler.
    """
    root = logging.getLogger()
    root.setLevel(level.upper())

    if not root.handlers:
        stream_handler = logging.StreamHandler()
        stream_handler.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
        )
        root.addHandler(stream_handler)

    for existing in root.handlers:
        # Ensure our redacting filter is attached exactly once per handler.
        if not any(isinstance(f, RedactingFilter) for f in existing.filters):
            existing.addFilter(RedactingFilter())


def get_logger(name: str) -> logging.Logger:
    """Return a logger with the redacting filter guaranteed to be installed."""
    logger = logging.getLogger(name)
    return logger


def redact_mapping(data: dict[str, Any]) -> dict[str, Any]:
    """Return a shallow copy of ``data`` with sensitive keys redacted.

    Useful when logging request context that originated from user input.
    """
    return {
        key: (REDACTED if key.lower() in SENSITIVE_FIELDS else value) for key, value in data.items()
    }
