#!/usr/bin/env python3
"""Seed the ontology_mapping table from cross-source entity aliases.

Reads semantic_context.entities from all sources, groups entities across
sources using union-find on shared names/aliases (case-insensitive), picks
a canonical name per group, and inserts ontology_mapping rows.

Usage:
    python scripts/seed_ontology_registry.py [--db-url URL] [--dry-run]
"""

from __future__ import annotations

import argparse
import json
import logging

import psycopg

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

DEFAULT_DB_URL = "postgresql://retrievalhub:retrievalhub@127.0.0.1:5434/retrievalhub"


# ---------------------------------------------------------------------------
# Union-Find
# ---------------------------------------------------------------------------

class UnionFind:
    """Simple disjoint-set with path compression and union by rank."""

    def __init__(self) -> None:
        self._parent: dict[int, int] = {}
        self._rank: dict[int, int] = {}

    def make_set(self, x: int) -> None:
        if x not in self._parent:
            self._parent[x] = x
            self._rank[x] = 0

    def find(self, x: int) -> int:
        while self._parent[x] != x:
            self._parent[x] = self._parent[self._parent[x]]
            x = self._parent[x]
        return x

    def union(self, a: int, b: int) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra == rb:
            return
        if self._rank[ra] < self._rank[rb]:
            ra, rb = rb, ra
        self._parent[rb] = ra
        if self._rank[ra] == self._rank[rb]:
            self._rank[ra] += 1


# ---------------------------------------------------------------------------
# Core logic
# ---------------------------------------------------------------------------

def load_source_entities(conn: psycopg.Connection) -> dict[str, list[dict]]:
    """Return {source_slug: [entity_dict, ...]} for sources with entities."""

    cur = conn.execute(
        "SELECT slug, semantic_context FROM source "
        "WHERE semantic_context IS NOT NULL"
    )
    result: dict[str, list[dict]] = {}
    for slug, sc_raw in cur.fetchall():
        if sc_raw is None:
            continue
        sc = json.loads(sc_raw) if isinstance(sc_raw, str) else sc_raw
        entities = sc.get("entities")
        if entities:
            result[slug] = entities
    return result


def build_groups(
    source_entities: dict[str, list[dict]],
) -> tuple[list[tuple[str, str]], dict[int, int]]:
    """Build union-find groups from cross-source name/alias overlaps.

    Returns (entity_list, uf_parent_map) where entity_list is a flat list
    of (source_slug, entity_name) pairs indexed by integer id.
    """

    # Flat list of (source_slug, entity_name) for indexing.
    entity_list: list[tuple[str, str]] = []
    for slug, entities in source_entities.items():
        for ent in entities:
            entity_list.append((slug, ent["name"]))

    uf = UnionFind()
    for i in range(len(entity_list)):
        uf.make_set(i)

    # Build a lookup: lowercase token -> list of entity indices that use it
    # (as name or alias).
    token_to_indices: dict[str, list[int]] = {}
    for i, (slug, _name) in enumerate(entity_list):
        ent = _entity_for(source_entities, slug, _name)
        tokens = {_name.lower()}
        for alias in ent.get("aliases", []):
            tokens.add(alias.lower())
        for tok in tokens:
            token_to_indices.setdefault(tok, []).append(i)

    # Union entities from DIFFERENT sources that share a token.
    for _tok, indices in token_to_indices.items():
        if len(indices) < 2:
            continue
        first = indices[0]
        for other in indices[1:]:
            if entity_list[first][0] != entity_list[other][0]:
                uf.union(first, other)
            else:
                # Same source -- only union cross-source.  But if a third
                # entity from a different source also shares the token, we
                # need pairwise checks.
                pass
        # Pairwise cross-source unions for the full list.
        for j in range(len(indices)):
            for k in range(j + 1, len(indices)):
                if entity_list[indices[j]][0] != entity_list[indices[k]][0]:
                    uf.union(indices[j], indices[k])

    return entity_list, {i: uf.find(i) for i in range(len(entity_list))}


def _entity_for(
    source_entities: dict[str, list[dict]], slug: str, name: str
) -> dict:
    for ent in source_entities[slug]:
        if ent["name"] == name:
            return ent
    raise KeyError(f"Entity {name!r} not found in source {slug!r}")


def pick_canonical(
    entity_list: list[tuple[str, str]],
    roots: dict[int, int],
) -> dict[int, str]:
    """For each group root, pick the canonical name.

    The name used by the most sources as the entity's primary name wins.
    Ties broken alphabetically (lowercase comparison).
    """

    # Group indices by root.
    groups: dict[int, list[int]] = {}
    for i, root in roots.items():
        groups.setdefault(root, []).append(i)

    canonical: dict[int, str] = {}
    for root, members in groups.items():
        # Count how many distinct sources use each entity name.
        name_source_count: dict[str, set[str]] = {}
        for idx in members:
            slug, name = entity_list[idx]
            name_source_count.setdefault(name, set()).add(slug)

        # Sort by (-count, lowercase name) to pick winner.
        best = sorted(
            name_source_count.items(),
            key=lambda item: (-len(item[1]), item[0].lower()),
        )[0][0]
        canonical[root] = best

    return canonical


def build_mappings(
    entity_list: list[tuple[str, str]],
    roots: dict[int, int],
    canonical: dict[int, str],
) -> list[tuple[str, str, str]]:
    """Return (canonical_name, source_slug, local_name) triples."""

    mappings: list[tuple[str, str, str]] = []
    for i, (slug, name) in enumerate(entity_list):
        root = roots[i]
        mappings.append((canonical[root], slug, name))
    return mappings


def insert_mappings(
    conn: psycopg.Connection,
    mappings: list[tuple[str, str, str]],
    dry_run: bool,
) -> int:
    """Insert ontology_mapping rows. Returns count of rows inserted."""

    inserted = 0
    for canon, slug, local in mappings:
        if dry_run:
            logger.info(
                "[DRY RUN] %s -> %s (source: %s)", local, canon, slug
            )
            inserted += 1
            continue
        cur = conn.execute(
            "INSERT INTO ontology_mapping "
            "(canonical_name, source_slug, local_name, created_at) "
            "VALUES (%s, %s, %s, NOW()) "
            "ON CONFLICT DO NOTHING",
            (canon, slug, local),
        )
        inserted += cur.rowcount
    return inserted


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db-url", default=DEFAULT_DB_URL)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    with psycopg.connect(args.db_url) as conn:
        source_entities = load_source_entities(conn)
        if not source_entities:
            logger.warning("No sources with entities found")
            return

        logger.info(
            "Loaded entities from %d sources: %s",
            len(source_entities),
            ", ".join(sorted(source_entities)),
        )

        entity_list, roots = build_groups(source_entities)
        canonical = pick_canonical(entity_list, roots)

        # Log the groups.
        groups: dict[int, list[int]] = {}
        for i, root in roots.items():
            groups.setdefault(root, []).append(i)

        for root, members in sorted(groups.items(), key=lambda x: canonical[x[0]].lower()):
            canon = canonical[root]
            member_strs = [
                f"{entity_list[i][1]} ({entity_list[i][0]})" for i in members
            ]
            logger.info(
                "Group %r: %s",
                canon,
                ", ".join(member_strs),
            )

        mappings = build_mappings(entity_list, roots, canonical)
        inserted = insert_mappings(conn, mappings, args.dry_run)

        if not args.dry_run:
            conn.commit()
            logger.info("Committed %d ontology_mapping rows", inserted)
        else:
            logger.info("[DRY RUN] Would insert %d rows", inserted)


if __name__ == "__main__":
    main()
