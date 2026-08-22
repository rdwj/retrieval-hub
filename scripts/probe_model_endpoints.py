"""Probe registered model endpoints and update health status in the catalog.

Queries all model_endpoint rows from the catalog database, sends GET /health
to each endpoint, and updates the status (healthy/unhealthy) and last_probed
timestamp via the model registry API.

Usage:
    python scripts/probe_model_endpoints.py
    python scripts/probe_model_endpoints.py --db-url postgresql+psycopg://...
    python scripts/probe_model_endpoints.py --timeout 10 --json-log
"""

from __future__ import annotations

import argparse
import json
import sys
import time

import httpx
from sqlalchemy import select

from retrieval_hub.db import create_db_engine, make_session_factory, session_scope
from retrieval_hub.model_registry import update_model_status
from retrieval_hub.models.model_endpoint import ModelEndpoint

DEFAULT_DB_URL = (
    "postgresql+psycopg://retrievalhub:retrievalhub@127.0.0.1:5434/retrievalhub"
)


def probe_endpoint(
    endpoint_url: str, timeout: float = 5.0
) -> tuple[str, float | None, str | None]:
    """Probe a single endpoint. Returns (status, latency_ms, error_msg)."""
    try:
        start = time.monotonic()
        resp = httpx.get(f"{endpoint_url}/health", timeout=timeout)
        latency_ms = (time.monotonic() - start) * 1000
        if resp.status_code < 400:
            return ("healthy", latency_ms, None)
        return ("unhealthy", latency_ms, f"HTTP {resp.status_code}")
    except httpx.TimeoutException:
        return ("unhealthy", None, "Timeout")
    except httpx.ConnectError as exc:
        return ("unhealthy", None, str(exc))
    except Exception as exc:
        return ("unhealthy", None, str(exc))


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Probe registered model endpoints and update health status.",
    )
    parser.add_argument(
        "--db-url",
        default=DEFAULT_DB_URL,
        help=f"SQLAlchemy URL for the catalog database (default: {DEFAULT_DB_URL})",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=5.0,
        help="HTTP timeout in seconds (default: 5)",
    )
    parser.add_argument(
        "--json-log",
        action="store_true",
        help="Emit structured JSON output instead of human-readable text",
    )
    args = parser.parse_args()

    engine = create_db_engine(args.db_url)
    factory = make_session_factory(engine)

    with session_scope(factory) as session:
        endpoints = (
            session.execute(select(ModelEndpoint)).scalars().all()
        )

        if not endpoints:
            if args.json_log:
                print(json.dumps({"event": "probe_summary", "total": 0}))
            else:
                print("No model endpoints registered.")
            return 2

        if not args.json_log:
            print(f"Probing {len(endpoints)} model endpoint(s)...")

        healthy_count = 0
        unhealthy_count = 0

        for ep in endpoints:
            status, latency_ms, error = probe_endpoint(ep.endpoint_url, args.timeout)

            if args.json_log:
                record: dict[str, object] = {
                    "event": "model_probe",
                    "model": ep.model_name,
                    "endpoint": ep.endpoint_url,
                    "status": status,
                }
                if latency_ms is not None:
                    record["latency_ms"] = round(latency_ms)
                if error is not None:
                    record["error"] = error
                print(json.dumps(record))
            else:
                if status == "healthy":
                    latency_str = f"({latency_ms:.0f}ms)" if latency_ms else ""
                    print(f"  healthy    {ep.model_name}  {latency_str}")
                else:
                    print(f"  UNHEALTHY  {ep.model_name}  {error}")

            if status == "healthy":
                healthy_count += 1
            else:
                unhealthy_count += 1

            update_model_status(session, ep.model_name, status)

    if args.json_log:
        print(json.dumps({
            "event": "probe_summary",
            "total": len(endpoints),
            "healthy": healthy_count,
            "unhealthy": unhealthy_count,
        }))
    else:
        print(f"\nResults: {healthy_count} healthy, {unhealthy_count} unhealthy")

    return 0 if unhealthy_count == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
