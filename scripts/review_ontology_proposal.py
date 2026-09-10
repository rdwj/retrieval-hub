"""Review and apply LLM-discovered entity definitions for a source.

Presents each proposed entity for human review. The data owner can
accept all, reject all, or review one-by-one with the option to edit
names, types, and definitions. Accepted entities are written to
semantic_context and mapped into the ontology registry.

Usage:

    # Review from a saved proposal file
    python scripts/review_ontology_proposal.py \\
        --slug my-source --from-file ontology-proposal-my-source.json

    # Discover live and review
    python scripts/review_ontology_proposal.py \\
        --slug my-source --llm-url https://llm.example.com/v1

    # Preview without applying (dry-run)
    python scripts/review_ontology_proposal.py \\
        --slug my-source --from-file proposal.json --dry-run
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

logger = logging.getLogger("review_ontology_proposal")

DEFAULT_DB_URL = (
    "postgresql+psycopg://retrievalhub:retrievalhub@127.0.0.1:5434/retrievalhub"
)
DEFAULT_VECTORS_DB_URL = (
    "postgresql+psycopg://retrievalhub:retrievalhub@127.0.0.1:5433/retrievalhub_vectors"
)


def _load_proposal(path: Path) -> list[dict]:
    data = json.loads(path.read_text(encoding="utf-8"))
    return data.get("entities", data if isinstance(data, list) else [])


def _find_canonical_match(
    entity: dict, lookup: dict[str, str]
) -> str | None:
    all_names = [entity["name"], *entity.get("aliases", [])]
    for n in all_names:
        match = lookup.get(n.lower())
        if match:
            return match
    return None


def _review_interactive(
    entities: list[dict], lookup: dict[str, str]
) -> list[dict]:
    """Interactive review: accept all, reject all, or one-by-one."""
    from retrieval_hub.ontology.discover import format_entity_for_review

    print(f"\n{'=' * 60}")
    print(f"  {len(entities)} entities proposed")
    print(f"{'=' * 60}\n")

    for i, entity in enumerate(entities, 1):
        match = _find_canonical_match(entity, lookup)
        print(f"[{i}/{len(entities)}]")
        print(format_entity_for_review(entity, match))
        print()

    print(f"{'=' * 60}")
    choice = input("\n  (A)ccept all / (R)eject all / (O)ne-by-one? [A]: ").strip().lower()

    if choice in ("r", "reject"):
        print("All entities rejected.")
        return []

    if choice in ("o", "one"):
        return _review_one_by_one(entities, lookup)

    return entities


def _review_one_by_one(
    entities: list[dict], lookup: dict[str, str]
) -> list[dict]:
    """Review each entity individually."""
    from retrieval_hub.ontology.discover import format_entity_for_review

    accepted = []
    for i, entity in enumerate(entities, 1):
        match = _find_canonical_match(entity, lookup)
        print(f"\n[{i}/{len(entities)}]")
        print(format_entity_for_review(entity, match))

        choice = input("  (A)ccept / (R)eject / (E)dit? [A]: ").strip().lower()

        if choice in ("r", "reject"):
            print(f"  Rejected: {entity['name']}")
            continue

        if choice in ("e", "edit"):
            entity = _edit_entity(entity)

        accepted.append(entity)
        print(f"  Accepted: {entity['name']}")

    return accepted


def _edit_entity(entity: dict) -> dict:
    """Prompt the user to edit entity fields."""
    edited = dict(entity)

    name = input(f"  Name [{entity['name']}]: ").strip()
    if name:
        edited["name"] = name

    etype = input(f"  Type [{entity.get('entity_type', '')}]: ").strip()
    if etype:
        edited["entity_type"] = etype

    defn = input(f"  Definition [{entity.get('definition', '')}]: ").strip()
    if defn:
        edited["definition"] = defn

    aliases_str = input(
        f"  Aliases (comma-sep) [{', '.join(entity.get('aliases', []))}]: "
    ).strip()
    if aliases_str:
        edited["aliases"] = [a.strip() for a in aliases_str.split(",") if a.strip()]

    return edited


def _apply_entities(
    slug: str,
    entities: list[dict],
    db_url: str,
    vectors_db_url: str,
) -> None:
    """Write entities to semantic_context and populate ontology mappings."""
    from sqlalchemy.orm.attributes import flag_modified

    from retrieval_hub.db import create_db_engine, make_session_factory, session_scope
    from retrieval_hub.models import Source
    from retrieval_hub.ontology import populate_ontology_for_source
    from retrieval_hub.ontology.doctor import check_missing_mappings, check_stale_mappings

    engine = create_db_engine(db_url)
    factory = make_session_factory(engine)
    with session_scope(factory) as session:
        source = session.query(Source).filter_by(slug=slug).one()
        sc = dict(source.semantic_context or {})
        existing_names = {e["name"] for e in sc.get("entities", [])}
        new = [e for e in entities if e["name"] not in existing_names]
        sc["entities"] = sc.get("entities", []) + new
        source.semantic_context = sc
        flag_modified(source, "semantic_context")
        session.flush()

        count = populate_ontology_for_source(slug, sc["entities"], session)
        print(f"\n  Applied: {len(new)} new entities, {count} ontology mappings created")

        # Doctor validation
        stale = check_stale_mappings(session, source_slug=slug, vectors_db_url=vectors_db_url)
        missing = check_missing_mappings(session, source_slug=slug)
        if stale:
            print(f"  WARN: {len(stale)} stale mappings detected")
            for f in stale[:3]:
                print(f"    - {f.get('local_name', '?')}: {f.get('reason', '?')}")
        if missing:
            print(f"  WARN: {len(missing)} missing mappings detected")
            for f in missing[:3]:
                print(f"    - {f.get('entity_type', '?')}")
        if not stale and not missing:
            print("  Doctor: no issues found")


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--slug", required=True, help="Source slug")
    parser.add_argument("--from-file", type=Path, help="Path to proposal JSON")
    parser.add_argument("--llm-url", help="LLM endpoint for live discovery")
    parser.add_argument("--llm-model", default="/mnt/models")
    parser.add_argument("--db-url", default=DEFAULT_DB_URL)
    parser.add_argument("--vectors-db-url", default=DEFAULT_VECTORS_DB_URL)
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Preview entities without applying",
    )
    args = parser.parse_args()

    if args.from_file:
        entities = _load_proposal(args.from_file)
        print(f"Loaded {len(entities)} entities from {args.from_file}")
    elif args.llm_url:
        from retrieval_hub.db import create_db_engine, make_session_factory, session_scope
        from retrieval_hub.models import PhysicalIndex, Source
        from retrieval_hub.ontology.discover import discover_entities

        engine = create_db_engine(args.db_url)
        with session_scope(make_session_factory(engine)) as session:
            source = session.query(Source).filter_by(slug=args.slug).one()
            pi = session.query(PhysicalIndex).filter_by(
                id=source.active_physical_index_id
            ).one()
            table = pi.location
            family = str(source.family)
            desc = source.description_short or args.slug
            name = source.name

        entities = discover_entities(
            vectors_db_url=args.vectors_db_url,
            table=table,
            db_url=args.db_url,
            source_name=name,
            source_family=family,
            source_description=desc,
            llm_url=args.llm_url,
            llm_model=args.llm_model,
        )
        if not entities:
            print("No entities discovered.")
            return 1
        print(f"Discovered {len(entities)} entities")
    else:
        print("Provide --from-file or --llm-url", file=sys.stderr)
        return 1

    # Build canonical lookup for showing matches
    from retrieval_hub.db import create_db_engine, make_session_factory, session_scope
    from retrieval_hub.ontology import _build_canonical_lookup

    engine = create_db_engine(args.db_url)
    with session_scope(make_session_factory(engine)) as session:
        lookup = _build_canonical_lookup(session)

    if args.dry_run:
        from retrieval_hub.ontology.discover import format_entity_for_review

        print(f"\n{'=' * 60}")
        print(f"  DRY RUN: {len(entities)} entities (not applied)")
        print(f"{'=' * 60}\n")
        for i, entity in enumerate(entities, 1):
            match = _find_canonical_match(entity, lookup)
            print(f"[{i}]")
            print(format_entity_for_review(entity, match))
            print()
        return 0

    accepted = _review_interactive(entities, lookup)
    if not accepted:
        print("No entities accepted.")
        return 0

    _apply_entities(args.slug, accepted, args.db_url, args.vectors_db_url)
    return 0


if __name__ == "__main__":
    sys.exit(main())
