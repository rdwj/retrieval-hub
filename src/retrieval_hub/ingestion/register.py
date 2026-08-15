"""Stage 7 of the ingestion pipeline: register the Source + Recipe + PhysicalIndex.

After chunks are written to the per-source pgvector table, ingestion has to
tell the catalog that the source exists, which recipe version built the
physical index, and which physical index is currently active. This module
performs that registration.

Idempotency: ``register_document_source`` is safe to re-run. If the source
already exists by slug, its ``active_physical_index_id`` is repointed at the
new physical index and the old one (if any) is left in place for lineage.
Recipe versions are de-duplicated by identical content hash so a re-run with
an unchanged recipe does not inflate the recipe history.
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.orm import Session

from retrieval_hub.models import PhysicalIndex, RecipeVersion, SamplePrompt, Source
from retrieval_hub.models.enums import (
    AccessVisibility,
    IndexHealth,
    PhysicalIndexBackend,
    PromptRole,
    SourceFamily,
    SourceStatus,
)

logger = logging.getLogger(__name__)


@dataclass
class RegistrationResult:
    """Summary of what ``register_document_source`` did."""

    source_id: str
    source_slug: str
    recipe_version_id: str
    recipe_version_number: int
    physical_index_id: str
    created_source: bool
    created_recipe_version: bool
    created_physical_index: bool


def _hash_recipe_content(content: dict[str, Any]) -> str:
    """Return a stable hash of a recipe content dict for de-duplication."""
    canonical = json.dumps(content, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def register_document_source(
    session: Session,
    *,
    slug: str,
    name: str,
    description_short: str,
    description_long: str,
    owner_team: str,
    owner_contacts: list[str],
    recipe_content: dict[str, Any],
    physical_index_location: str,
    document_count: int,
    chunk_count: int,
    sample_prompts: list[tuple[str, str]] | None = None,
    usage_rules: dict[str, Any] | None = None,
    triggered_by: str = "script:step4_ingest",
    family: SourceFamily = SourceFamily.DOCUMENT,
) -> RegistrationResult:
    """Register (or update) a ``document``-family source in the catalog.

    Parameters
    ----------
    session:
        Live SQLAlchemy session against the catalog database.
    slug:
        Stable URL-safe slug for the source.
    name:
        Human-readable source name.
    description_short, description_long:
        Browse-time and detail-time descriptions.
    owner_team:
        Team that owns the source.
    owner_contacts:
        Contact email addresses for the owning team.
    recipe_content:
        The full recipe body as a JSON-serializable dict (parser, chunker,
        embedding, backend). Stored as-is on ``RecipeVersion.content``.
    physical_index_location:
        Name of the pgvector table where chunks were written.
    document_count:
        Number of distinct source documents represented in the index.
    chunk_count:
        Number of chunks written.
    sample_prompts:
        Optional list of ``(llm_family_pattern, prompt_text)`` pairs to
        register alongside the source.
    triggered_by:
        Identity string recorded on any new audit-relevant fields. Defaults
        to the hand-run script identifier.

    Returns
    -------
    RegistrationResult
        Summary of what was created or updated.
    """
    now = datetime.now(UTC)

    # --- Source -------------------------------------------------------
    source = session.query(Source).filter(Source.slug == slug).one_or_none()
    created_source = False
    if source is None:
        source = Source(
            slug=slug,
            name=name,
            family=family,
            status=SourceStatus.CURATED,
            visibility=AccessVisibility.PUBLIC,
            description_short=description_short,
            description_long=description_long,
            owner_team=owner_team,
            owner_contacts=list(owner_contacts),
            maintainers=[],
            rewriter_metadata={"enabled": False},
            agent_write_policy={"allowed": False},
            usage_rules=usage_rules,
            access={"visibility": "public", "allowed_groups": []},
            lineage_origin={
                "kind": "hand_run_script",
                "config": {"triggered_by": triggered_by},
            },
            refresh_cadence="on_demand",
            created_at=now,
            updated_at=now,
            created_by=triggered_by,
            updated_by=triggered_by,
        )
        session.add(source)
        session.flush()  # populate source.id
        created_source = True
        logger.info("register.created_source slug=%s id=%s", slug, source.id)
    else:
        source.name = name
        source.description_short = description_short
        source.description_long = description_long
        if usage_rules is not None:
            source.usage_rules = usage_rules
        source.updated_at = now
        source.updated_by = triggered_by
        logger.info("register.updated_source slug=%s id=%s", slug, source.id)

    # --- RecipeVersion ------------------------------------------------
    recipe_hash = _hash_recipe_content(recipe_content)
    existing_versions = (
        session.query(RecipeVersion)
        .filter(RecipeVersion.source_id == source.id)
        .order_by(RecipeVersion.version_number.asc())
        .all()
    )

    matching = None
    for rv in existing_versions:
        if _hash_recipe_content(rv.content or {}) == recipe_hash:
            matching = rv
            break

    created_recipe_version = False
    if matching is not None:
        recipe_version = matching
        logger.info(
            "register.reusing_recipe_version id=%s version=%d",
            recipe_version.id,
            recipe_version.version_number,
        )
    else:
        next_version = (existing_versions[-1].version_number + 1) if existing_versions else 1
        recipe_version = RecipeVersion(
            source_id=source.id,
            version_number=next_version,
            content=dict(recipe_content),
            created_at=now,
            created_by=triggered_by,
        )
        session.add(recipe_version)
        session.flush()
        created_recipe_version = True
        logger.info(
            "register.created_recipe_version id=%s version=%d",
            recipe_version.id,
            recipe_version.version_number,
        )

    # --- PhysicalIndex -------------------------------------------------
    physical_index = PhysicalIndex(
        source_id=source.id,
        recipe_version_id=recipe_version.id,
        backend_kind=PhysicalIndexBackend.PGVECTOR,
        location=physical_index_location,
        built_at=now,
        health=IndexHealth.OK,
        document_count=document_count,
        build_metadata={
            "chunk_count": chunk_count,
            "triggered_by": triggered_by,
        },
    )
    session.add(physical_index)
    session.flush()

    source.active_physical_index_id = physical_index.id

    # --- SamplePrompts -------------------------------------------------
    if sample_prompts:
        session.query(SamplePrompt).filter(SamplePrompt.source_id == source.id).delete()
        for pattern, text in sample_prompts:
            session.add(
                SamplePrompt(
                    source_id=source.id,
                    applies_to_llm_family=pattern,
                    role=PromptRole.SYSTEM,
                    text=text,
                    created_at=now,
                )
            )

    session.commit()
    return RegistrationResult(
        source_id=source.id,
        source_slug=source.slug,
        recipe_version_id=recipe_version.id,
        recipe_version_number=recipe_version.version_number,
        physical_index_id=physical_index.id,
        created_source=created_source,
        created_recipe_version=created_recipe_version,
        created_physical_index=True,
    )
