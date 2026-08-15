"""Map ORM models to the UI-facing JSON shape.

``map_source_to_ui`` is the core function: it takes a Source ORM object and
a SQLAlchemy session, queries related tables (recipe versions, physical index,
evals, sample prompts, ingestion runs), and returns a dict that serializes to
the ``SourceResponse`` Pydantic model.
"""

from __future__ import annotations

import logging
from typing import Any

import yaml
from sqlalchemy.orm import Session

from retrieval_hub.models.eval import EvalRun
from retrieval_hub.models.ingestion import IngestionRun
from retrieval_hub.models.recipe import RecipeVersion
from retrieval_hub.models.source import PhysicalIndex, SamplePrompt, Source

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _iso(dt: Any) -> str | None:
    """Convert a datetime to an ISO 8601 string, or return None."""
    if dt is None:
        return None
    try:
        return dt.isoformat()
    except Exception:
        return str(dt)


def _safe_get(d: dict | None, *keys: str, default: Any = None) -> Any:
    """Walk nested dict keys, returning *default* if any key is missing."""
    val = d
    for k in keys:
        if not isinstance(val, dict):
            return default
        val = val.get(k, default)
    return val


# ---------------------------------------------------------------------------
# Recipe mapping
# ---------------------------------------------------------------------------


def _map_recipe(rv: RecipeVersion | None) -> dict[str, Any]:
    """Map a RecipeVersion ORM row to the UI Recipe shape."""
    if rv is None:
        return {
            "version": 0,
            "parser_kind": "",
            "chunker_kind": "",
            "chunker_summary": "",
            "embedding_model": "",
            "embedding_dimension": 0,
            "backend_kind": "",
            "backend_location": "",
            "raw_yaml": "",
        }

    content = rv.content or {}

    chunk_size = _safe_get(content, "chunker", "chunk_size_tokens", default=0)
    overlap = _safe_get(content, "chunker", "overlap_tokens", default=0)
    chunker_summary = ""
    if chunk_size:
        chunker_summary = f"{chunk_size} tok"
        if overlap:
            chunker_summary += f" / {overlap} overlap"

    try:
        raw_yaml = yaml.dump(content, default_flow_style=False, sort_keys=False)
    except Exception:
        raw_yaml = str(content)

    return {
        "version": rv.version_number,
        "parser_kind": _safe_get(content, "parser", "kind", default=""),
        "chunker_kind": _safe_get(content, "chunker", "kind", default=""),
        "chunker_summary": chunker_summary,
        "embedding_model": _safe_get(content, "embedding", "model", default=""),
        "embedding_dimension": _safe_get(content, "embedding", "dimension", default=0),
        "backend_kind": _safe_get(content, "backend", "kind", default=""),
        "backend_location": _safe_get(
            content, "backend", "table", default=""
        ) or _safe_get(content, "backend", "database", default="")
        or _safe_get(content, "backend", "graph", default=""),
        "raw_yaml": raw_yaml,
    }


# ---------------------------------------------------------------------------
# Retrieval pattern mapping
# ---------------------------------------------------------------------------


def _map_retrieval_patterns(
    content: dict[str, Any] | None,
) -> tuple[str, list[dict[str, Any]]]:
    """Extract retrieval default pattern and supported patterns from recipe content."""
    if content is None:
        return "vector_ann", []

    retrieval = content.get("retrieval", {})
    if not isinstance(retrieval, dict):
        return "vector_ann", []

    default_pattern = retrieval.get("default_pattern", "vector_ann")
    supported_names = retrieval.get("supported_patterns", [])
    parameters_map = retrieval.get("parameters", {})

    if not isinstance(parameters_map, dict):
        parameters_map = {}

    patterns: list[dict[str, Any]] = []
    for name in supported_names:
        params = parameters_map.get(name, {})
        if not isinstance(params, dict):
            params = {}
        patterns.append({"pattern": name, "parameters": params})

    return default_pattern, patterns


# ---------------------------------------------------------------------------
# Main mapper
# ---------------------------------------------------------------------------


def map_source_to_ui(source: Source, session: Session) -> dict[str, Any]:
    """Transform a Source ORM object into the dict shape the UI expects.

    This queries related tables (recipe versions, physical index, evals,
    sample prompts, ingestion runs) using the provided session.
    """

    # -- Owner ---------------------------------------------------------------
    owner = {
        "team": source.owner_team or "",
        "contacts": source.owner_contacts or [],
        "maintainers": source.maintainers or [],
    }

    # -- Active recipe version -----------------------------------------------
    active_rv: RecipeVersion | None = None
    recipe_content: dict[str, Any] | None = None
    if source.recipe_version_id:
        active_rv = (
            session.query(RecipeVersion)
            .filter(RecipeVersion.id == source.recipe_version_id)
            .one_or_none()
        )
        if active_rv:
            recipe_content = active_rv.content

    recipe = _map_recipe(active_rv)

    # -- Recipe version history ----------------------------------------------
    all_rvs = (
        session.query(RecipeVersion)
        .filter(RecipeVersion.source_id == source.id)
        .order_by(RecipeVersion.version_number.desc())
        .all()
    )
    recipe_version_history = [
        {
            "version": rv.version_number,
            "active_since": _iso(rv.created_at) or "",
            "author": rv.created_by or "",
            "summary": f"Recipe version {rv.version_number}",
        }
        for rv in all_rvs
    ]

    # -- Retrieval patterns --------------------------------------------------
    retrieval_default, retrieval_patterns = _map_retrieval_patterns(recipe_content)

    # -- Active physical index -----------------------------------------------
    active_pi: PhysicalIndex | None = None
    pi_info: dict[str, Any] | None = None
    size_summary = "(no index yet)"
    chunk_count_total: int | None = None

    if source.active_physical_index_id:
        active_pi = (
            session.query(PhysicalIndex)
            .filter(PhysicalIndex.id == source.active_physical_index_id)
            .one_or_none()
        )

    if active_pi is not None:
        # Resolve the recipe version number for this physical index
        pi_rv_number = 0
        if active_pi.recipe_version_id:
            pi_rv = (
                session.query(RecipeVersion)
                .filter(RecipeVersion.id == active_pi.recipe_version_id)
                .one_or_none()
            )
            if pi_rv:
                pi_rv_number = pi_rv.version_number

        pi_info = {
            "id": active_pi.id,
            "recipe_version": pi_rv_number,
            "backend_kind": str(active_pi.backend_kind),
            "location": active_pi.location,
            "built_at": _iso(active_pi.built_at),
            "document_count": active_pi.document_count,
            "health": str(active_pi.health),
        }

        doc_count = active_pi.document_count
        size_summary = f"{doc_count:,} documents"

        if active_pi.build_metadata and isinstance(active_pi.build_metadata, dict):
            chunk_count_total = active_pi.build_metadata.get("chunk_count")

    # -- Evals ---------------------------------------------------------------
    eval_runs = (
        session.query(EvalRun)
        .filter(
            EvalRun.source_id == source.id,
            EvalRun.status == "completed",
        )
        .order_by(EvalRun.started_at.desc().nullslast())
        .all()
    )

    evals: list[dict[str, Any]] = []
    for er in eval_runs:
        scores = er.scores or {}
        evals.append(
            {
                "llm": er.llm,
                "recall_at_5": scores.get("recall_at_5", 0.0),
                "mrr": scores.get("mrr", 0.0),
                "rewrite_lift_at_5": scores.get("rewrite_lift_at_5"),
                "source_system": str(er.execution_backend),
                "eval_run_id": er.id,
                "mlflow_run_id": er.mlflow_run_id,
                "run_at": _iso(er.started_at) or "",
            }
        )

    # -- Rewriter metadata ---------------------------------------------------
    rw_raw = source.rewriter_metadata or {}
    rewriter = {
        "enabled": rw_raw.get("enabled", False),
        "shared_template_pointer": rw_raw.get("shared_template_pointer"),
        "shared_template_version": rw_raw.get("shared_template_version"),
        "vocabulary_mappings": rw_raw.get("vocabulary_mappings", []),
        "sample_queries": rw_raw.get("sample_queries", []),
        "domain_notes": rw_raw.get("domain_notes", ""),
        "schema_hints": rw_raw.get("schema_hints"),
        "prompt_override_id": rw_raw.get("prompt_override_id"),
        "default_llm": rw_raw.get("default_llm", ""),
        "llm_resolution": rw_raw.get("llm_resolution", "default"),
        "max_rewrites": rw_raw.get("max_rewrites", 0),
        "metadata_version": rw_raw.get("metadata_version", 1),
    }

    # -- Agent write policy --------------------------------------------------
    awp_raw = source.agent_write_policy or {}
    agent_write_policy = {
        "allowed": awp_raw.get("allowed", False),
        "scope_required": awp_raw.get("scope_required", ""),
        "allowed_groups": awp_raw.get("allowed_groups", []),
        "write_modes": awp_raw.get("write_modes", []),
        "write_validation": awp_raw.get("write_validation"),
        "recent_write_activity_summary": awp_raw.get(
            "recent_write_activity_summary"
        ),
    }

    # -- Sample prompts ------------------------------------------------------
    prompts = (
        session.query(SamplePrompt)
        .filter(SamplePrompt.source_id == source.id)
        .all()
    )
    sample_prompts = [
        {
            "applies_to_llm_family": sp.applies_to_llm_family,
            "role": str(sp.role),
            "text": sp.text,
        }
        for sp in prompts
    ]

    # -- Lineage -------------------------------------------------------------
    origin = source.lineage_origin or {}
    lineage: dict[str, Any] = {
        "origin_kind": origin.get("kind", "file_upload"),
        "origin_config": {
            k: v for k, v in origin.items() if k != "kind"
        },
        "refresh_cadence": source.refresh_cadence or "on_demand",
        "last_refresh_at": _iso(source.last_refresh_at),
        "next_scheduled_refresh_at": None,
        "ingestion_runs": [],
    }

    # Query ingestion runs
    try:
        ing_runs = (
            session.query(IngestionRun)
            .filter(IngestionRun.source_id == source.id)
            .order_by(IngestionRun.started_at.desc().nullslast())
            .limit(10)
            .all()
        )
        for ir in ing_runs:
            duration = 0.0
            if ir.started_at and ir.completed_at:
                duration = (ir.completed_at - ir.started_at).total_seconds()

            doc_count_ir = 0
            if ir.result_manifest and isinstance(ir.result_manifest, dict):
                doc_count_ir = ir.result_manifest.get("document_count", 0)

            lineage["ingestion_runs"].append(
                {
                    "id": ir.id,
                    "status": str(ir.status),
                    "started_at": _iso(ir.started_at) or "",
                    "duration_seconds": duration,
                    "document_count": doc_count_ir,
                    "triggered_by": ir.triggered_by or "",
                }
            )
    except Exception:
        # Table might not exist yet; degrade gracefully
        logger.debug("Could not query ingestion_run table", exc_info=True)

    # -- Access --------------------------------------------------------------
    access_raw = source.access
    if access_raw and isinstance(access_raw, dict):
        access = {
            "visibility": access_raw.get("visibility", str(source.visibility)),
            "allowed_groups": access_raw.get("allowed_groups", []),
        }
    else:
        access = {
            "visibility": str(source.visibility),
            "allowed_groups": [],
        }

    # -- Assemble the full response ------------------------------------------
    return {
        "id": source.id,
        "slug": source.slug,
        "name": source.name,
        "family": str(source.family),
        "status": str(source.status),
        "owner": owner,
        "description_short": source.description_short or "",
        "description_long": source.description_long or "",
        "intended_use": None,
        "out_of_scope_use": None,
        "known_limitations": None,
        "domain_tags": [],
        "languages": ["en"],
        "citation_format": None,
        "created_at": _iso(source.created_at) or "",
        "updated_at": _iso(source.updated_at) or "",
        "recipe": recipe,
        "recipe_version_history": recipe_version_history,
        "retrieval_default_pattern": retrieval_default,
        "retrieval_supported_patterns": retrieval_patterns,
        "active_physical_index": pi_info,
        "size_summary": size_summary,
        "chunk_count_total": chunk_count_total,
        "evals": evals,
        "latency_p50_ms": 0,
        "latency_p95_ms": 0,
        "cost_estimate_hint": None,
        "rewriter": rewriter,
        "agent_write_policy": agent_write_policy,
        "sample_prompts": sample_prompts,
        "lineage": lineage,
        "access": access,
        "health_flags": [],
        "usage_rules": source.usage_rules,
    }
