"""Liveness and readiness endpoints.

``/health`` is the cheap liveness probe — returns 200 as long as the process
is answering. ``/ready`` is the readiness probe — returns 200 only if the
database is reachable. OpenShift deployments wire both to the corresponding
probe kinds; a failing ``/ready`` quiesces the pod without killing it.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, status
from fastapi.responses import JSONResponse
from sqlalchemy import text

from retrieval_hub_auth import __version__
from retrieval_hub_auth.app_state import AppState
from retrieval_hub_auth.dependencies import get_app_state

router = APIRouter(tags=["observability"])


@router.get("/health", response_model=None)
async def health_endpoint() -> dict[str, Any]:
    """Basic liveness info. Does not touch the database."""
    return {"status": "ok", "service": "retrieval-hub-auth", "version": __version__}


@router.get("/ready", response_model=None)
async def ready_endpoint(state: AppState = Depends(get_app_state)) -> Any:
    """Readiness: returns 200 iff the database is reachable."""
    try:
        with state.engine.connect() as connection:
            connection.execute(text("SELECT 1"))
    except Exception as exc:
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={"status": "not_ready", "reason": str(exc)},
        )
    return {"status": "ready"}
