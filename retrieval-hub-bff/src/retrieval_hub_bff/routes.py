"""API routes for the RetrievalHub BFF.

Endpoints:
    GET /api/health          -- liveness check
    GET /api/sources         -- list curated/published sources
    GET /api/sources/{slug}  -- single source detail
"""

from __future__ import annotations

import logging
import os

import httpx
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from retrieval_hub.db.engine import create_db_engine, make_session_factory
from retrieval_hub.models.enums import SourceStatus
from retrieval_hub.models.source import Source
from retrieval_hub_bff.mappers import map_source_to_ui
from retrieval_hub_bff.schemas import SourceResponse

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api")

# ---------------------------------------------------------------------------
# Database dependency (lazy singletons, same pattern as the MCP server)
# ---------------------------------------------------------------------------

_engine = None
_session_factory = None


def _get_engine():
    global _engine
    if _engine is None:
        _engine = create_db_engine()
    return _engine


def _get_session_factory():
    global _session_factory
    if _session_factory is None:
        _session_factory = make_session_factory(_get_engine())
    return _session_factory


def _get_session() -> Session:
    factory = _get_session_factory()
    return factory()


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.get("/health")
async def health():
    return {"status": "ok"}


@router.get("/sources", response_model=list[SourceResponse])
async def list_sources():
    """Return all sources with status curated or published."""
    session = _get_session()
    try:
        sources = (
            session.query(Source)
            .filter(
                Source.status.in_(
                    [SourceStatus.CURATED, SourceStatus.PUBLISHED]
                )
            )
            .order_by(Source.name)
            .all()
        )

        mcp_public_url = os.environ.get("MCP_PUBLIC_URL", "")

        results = []
        for s in sources:
            data = map_source_to_ui(s, session)
            if mcp_public_url:
                data["mcp_endpoint"] = mcp_public_url
            results.append(data)

        return results
    finally:
        session.close()


@router.get("/sources/{slug}", response_model=SourceResponse)
async def get_source(slug: str):
    """Return a single source by slug, or 404."""
    session = _get_session()
    try:
        source = (
            session.query(Source).filter(Source.slug == slug).one_or_none()
        )
        if source is None:
            raise HTTPException(
                status_code=404,
                detail=f"Source with slug {slug!r} not found",
            )

        data = map_source_to_ui(source, session)

        mcp_public_url = os.environ.get("MCP_PUBLIC_URL", "")
        if mcp_public_url:
            data["mcp_endpoint"] = mcp_public_url

        return data
    finally:
        session.close()


# ---------------------------------------------------------------------------
# Playground: retrieve + generate
# ---------------------------------------------------------------------------

LLM_URL = os.environ.get(
    "LLM_ENDPOINT_URL",
    "http://gpt-oss-120b-direct.gpt-oss-120b-model.svc:8080/v1/chat/completions",
)
LLM_MODEL = os.environ.get("LLM_MODEL_ID", "/mnt/models")
MCP_INTERNAL_URL = os.environ.get(
    "MCP_INTERNAL_URL",
    "http://retrieval-hub-mcp:8080/mcp",
)


class PlaygroundRequest(BaseModel):
    query: str
    source_slug: str
    top_k: int = 5


class PlaygroundHit(BaseModel):
    text: str
    score: float
    doc_title: str
    doc_url: str
    doc_section: str | None = None


class PlaygroundResponse(BaseModel):
    hits: list[PlaygroundHit]
    answer: str
    usage_rules: dict | None = None
    elapsed_ms: int = 0
    model: str = ""


@router.post("/playground/query", response_model=PlaygroundResponse)
async def playground_query(req: PlaygroundRequest):
    """Retrieve chunks via the core library, then generate an answer with the hosted LLM."""
    import time

    from retrieval_hub.retrieval.api import (
        SourceNotFoundError,
        SourceNotQueryableError,
    )
    from retrieval_hub.retrieval.api import (
        query as retrieval_query,
    )

    t0 = time.monotonic()

    session = _get_session()
    try:
        results = retrieval_query(
            source_slug=req.source_slug,
            query_text=req.query,
            session=session,
            top_k=req.top_k,
        )
        source = session.query(Source).filter(
            Source.slug == req.source_slug
        ).one_or_none()
        usage_rules = source.usage_rules if source else None
    except SourceNotFoundError as exc:
        raise HTTPException(404, f"Source {req.source_slug!r} not found") from exc
    except SourceNotQueryableError as exc:
        raise HTTPException(400, f"Source {req.source_slug!r} has no active index") from exc
    finally:
        session.close()

    raw_hits = [
        {"text": r.text, "score": r.score, "doc_title": r.doc_title,
         "doc_url": r.doc_url, "doc_section": r.doc_section}
        for r in results
    ]

    hits = [
        PlaygroundHit(
            text=h.get("text", "")[:1000],
            score=h.get("score", 0.0),
            doc_title=h.get("doc_title", ""),
            doc_url=h.get("doc_url", ""),
            doc_section=h.get("doc_section"),
        )
        for h in raw_hits
    ]

    context = "\n\n---\n\n".join(
        f"[{h.doc_title} — {h.doc_section or 'N/A'}]\n{h.text}" for h in hits
    )

    citation_rule = ""
    if usage_rules and usage_rules.get("citation"):
        citation_rule = f"\n\nIMPORTANT: {usage_rules['citation']}"
    scope_rule = ""
    if usage_rules and usage_rules.get("scope_disclaimer"):
        scope_rule = f"\n{usage_rules['scope_disclaimer']}"

    messages = [
        {
            "role": "system",
            "content": (
                "You are a clinical reference assistant. Answer the user's "
                "question using ONLY the retrieved context below. Cite the "
                "source document title and section for every claim."
                f"{citation_rule}{scope_rule}"
            ),
        },
        {
            "role": "user",
            "content": f"Context:\n{context}\n\nQuestion: {req.query}",
        },
    ]

    answer = ""
    try:
        async with httpx.AsyncClient(timeout=120.0) as client:
            resp = await client.post(
                LLM_URL,
                json={
                    "model": LLM_MODEL,
                    "messages": messages,
                    "max_tokens": 1024,
                    "temperature": 0.1,
                },
            )
            resp.raise_for_status()
            data = resp.json()
            answer = data["choices"][0]["message"]["content"]
    except Exception as exc:
        logger.warning("LLM call failed: %s", exc)
        answer = f"(LLM generation failed: {exc})"

    elapsed = int((time.monotonic() - t0) * 1000)

    return PlaygroundResponse(
        hits=hits,
        answer=answer,
        usage_rules=usage_rules,
        elapsed_ms=elapsed,
        model=LLM_MODEL,
    )
