"""Incremental ontology registry population.

Provides ``populate_ontology_for_source`` to add a single source's entities
to the ``ontology_mapping`` table, matching against existing canonical groups
by name/alias overlap (case-insensitive).  This is the incremental counterpart
to ``scripts/seed_ontology_registry.py`` which does a full cross-source
rebuild with union-find.
"""

from __future__ import annotations

import logging

from sqlalchemy.orm import Session

from retrieval_hub.models.ontology import OntologyMapping

logger = logging.getLogger(__name__)


def _build_canonical_lookup(session: Session) -> dict[str, str]:
    """Build a case-insensitive lookup from all existing registry names.

    Returns ``{lowercase_name: canonical_name}`` covering both canonical
    names and local names so that any overlap finds the right group.
    """
    rows = session.query(
        OntologyMapping.canonical_name,
        OntologyMapping.local_name,
    ).all()

    lookup: dict[str, str] = {}
    for canonical, local in rows:
        lookup.setdefault(canonical.lower(), canonical)
        lookup.setdefault(local.lower(), canonical)
    return lookup


def populate_ontology_for_source(
    source_slug: str,
    entities: list[dict],
    session: Session,
) -> int:
    """Upsert ontology_mapping rows for a source's entities.

    For each entity, checks if any of its names or aliases match an
    existing canonical group (case-insensitive).  If a match is found,
    uses that canonical_name.  Otherwise the entity's primary name
    becomes a new canonical name.

    Returns the number of new rows inserted (duplicates are skipped
    via the unique constraint).
    """
    if not entities:
        return 0

    lookup = _build_canonical_lookup(session)
    inserted = 0

    for entity in entities:
        name = entity.get("name")
        if not name:
            continue

        aliases = entity.get("aliases", [])
        all_names = [name, *aliases]

        canonical = None
        for n in all_names:
            canonical = lookup.get(n.lower())
            if canonical:
                break

        if canonical is None:
            canonical = name
            lookup[name.lower()] = canonical

        existing = (
            session.query(OntologyMapping)
            .filter(
                OntologyMapping.canonical_name == canonical,
                OntologyMapping.source_slug == source_slug,
                OntologyMapping.local_name == name,
            )
            .one_or_none()
        )
        if existing is None:
            session.add(
                OntologyMapping(
                    canonical_name=canonical,
                    source_slug=source_slug,
                    local_name=name,
                )
            )
            inserted += 1
            lookup[name.lower()] = canonical

    session.flush()
    logger.info(
        "Populated %d ontology_mapping row(s) for source %s",
        inserted,
        source_slug,
    )
    return inserted
