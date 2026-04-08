"""Service-scoped state container for retrieval-hub-auth.

FastAPI's dependency-injection system wants providers, not globals, but the
underlying objects the providers return (the database engine, the key ring,
the token issuer, the rate limiter) are long-lived service singletons. We
put them in a single container attached to ``app.state`` so bootstrap code,
tests, and dependency providers can all reach them in a uniform way.
"""

from __future__ import annotations

from dataclasses import dataclass
from threading import Lock
from time import monotonic

from sqlalchemy import Engine
from sqlalchemy.orm import Session, sessionmaker

from retrieval_hub_auth.backends.base import IdPBackend
from retrieval_hub_auth.config import AuthSettings
from retrieval_hub_auth.keys.rotation import KeyRing
from retrieval_hub_auth.tokens.issuer import TokenIssuer
from retrieval_hub_auth.tokens.validator import TokenValidator


class InMemoryRateLimiter:
    """Token-bucket-ish rate limiter scoped per client.

    Good enough for development and single-instance deploys. A production
    deploy in front of real agents will want a shared backend (Redis,
    OpenShift's own rate-limit Operator, etc.) but that's a later step.

    The limiter uses a sliding 60-second window: each client gets a
    per-minute allowance that refills as old hits age out.
    """

    def __init__(self, requests_per_minute: int) -> None:
        """Create an empty limiter with the given per-client limit."""
        self._requests_per_minute = requests_per_minute
        self._hits: dict[str, list[float]] = {}
        self._lock = Lock()

    def check(self, client_id: str) -> bool:
        """Return True if ``client_id`` is below its per-minute allowance.

        Also records the hit. Thread-safe.
        """
        now = monotonic()
        cutoff = now - 60.0
        with self._lock:
            hits = [h for h in self._hits.get(client_id, []) if h > cutoff]
            if len(hits) >= self._requests_per_minute:
                self._hits[client_id] = hits
                return False
            hits.append(now)
            self._hits[client_id] = hits
            return True

    def reset(self) -> None:
        """Clear all recorded hits (for tests)."""
        with self._lock:
            self._hits.clear()


@dataclass(slots=True)
class AppState:
    """The long-lived objects the service's routes depend on."""

    settings: AuthSettings
    engine: Engine
    session_factory: sessionmaker[Session]
    key_ring: KeyRing
    backend: IdPBackend
    issuer: TokenIssuer
    validator: TokenValidator
    rate_limiter: InMemoryRateLimiter
