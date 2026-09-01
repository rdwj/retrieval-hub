#!/usr/bin/env python3
"""Extract a hypertension-centered subgraph from SNOMED-CT RF2 files.

Reads the Full-release SNOMED-CT RF2 files (concepts, descriptions, text
definitions, relationships), performs a multi-strategy BFS from hypertension
seed concepts, and writes the subgraph as nodes.tsv and edges.tsv formatted
for RetrievalHub's graph chunker.

For Full-release files, each record ID may have multiple rows (one per
effectiveTime).  We keep only the latest row per ID, then filter to
active=1.

Usage:
    python scripts/extract_snomed_subgraph.py [--snomed-dir DIR] [--output-dir DIR]
"""

from __future__ import annotations

import argparse
import csv
import json
import logging
import re
import sys
from collections import defaultdict, deque
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(name)s %(levelname)s %(message)s",
)
logger = logging.getLogger(__name__)

# --- Defaults ---

DATA_SOURCES = Path(__file__).resolve().parent.parent.parent / (
    "retrieval-hub-data-sources"
)
DEFAULT_OUTPUT_DIR = DATA_SOURCES / "snomed-ct-hypertension"

# --- SNOMED-CT constants ---

SEED_CONCEPTS = [
    "38341003",  # Hypertensive disorder, systemic arterial
    "59621000",  # Essential hypertension
]

# Description typeIds
TYPEID_FSN = "900000000000003001"
TYPEID_SYNONYM = "900000000000013009"

# Relationship type concept IDs and human-readable names
RELATIONSHIP_TYPES: dict[str, str] = {
    "116680003": "IS_A",
    "363698007": "FINDING_SITE",
    "116676008": "ASSOCIATED_MORPHOLOGY",
    "363705008": "HAS_DEFINITIONAL_MANIFESTATION",
    "363713009": "HAS_INTERPRETATION",
    "363714003": "INTERPRETS",
    "246075003": "CAUSATIVE_AGENT",
    "405813007": "PROCEDURE_SITE_DIRECT",
}

IS_A_TYPEID = "116680003"

# Semantic tags that indicate taxonomic context targets
TAXONOMIC_CONTEXT_TAGS = {"body structure", "observable entity"}

# Maximum ancestor levels for IS_A upward traversal
MAX_ANCESTOR_LEVELS = 3

# Regex to extract the semantic tag from an FSN
_SEMANTIC_TAG_RE = re.compile(r"\(([^)]+)\)\s*$")


def find_snomed_dir(base: Path) -> Path | None:
    """Find the SNOMED-CT RF2 directory under the data-sources path.

    Looks for a directory matching SnomedCT_* containing
    Full/Terminology/.
    """
    snomed_base = base / "snomed-ct"
    if not snomed_base.exists():
        return None
    for candidate in sorted(snomed_base.iterdir()):
        if candidate.name.startswith("SnomedCT_"):
            terminology = candidate / "Full" / "Terminology"
            if terminology.is_dir():
                return terminology
    return None


def find_rf2_file(directory: Path, prefix: str) -> Path | None:
    """Find an RF2 file by prefix in the given directory."""
    matches = sorted(directory.glob(f"{prefix}*.txt"))
    return matches[0] if matches else None


def extract_semantic_tag(fsn: str) -> str:
    """Extract the semantic tag from a Fully Specified Name.

    "Essential hypertension (disorder)" -> "disorder"
    """
    m = _SEMANTIC_TAG_RE.search(fsn)
    return m.group(1) if m else ""


def tag_to_entity_type(tag: str) -> str:
    """Convert a semantic tag to a title-cased entity_type.

    "body structure" -> "Body Structure"
    "disorder" -> "Disorder"
    """
    return tag.title() if tag else "Unknown"


def strip_semantic_tag(fsn: str) -> str:
    """Remove the semantic tag from an FSN to get a bare term.

    "Essential hypertension (disorder)" -> "Essential hypertension"
    """
    return _SEMANTIC_TAG_RE.sub("", fsn).strip()


# --- RF2 Full-release deduplication ---


def load_latest_active_concepts(path: Path) -> set[str]:
    """Load active concept IDs from the Full concept file.

    For each concept ID, keeps only the row with the latest
    effectiveTime, then filters to active=1.
    """
    logger.info("Loading concepts from %s", path)
    latest: dict[str, tuple[str, str]] = {}  # id -> (effectiveTime, active)
    with open(path, newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh, delimiter="\t")
        for row in reader:
            cid = row["id"]
            et = row["effectiveTime"]
            prev = latest.get(cid)
            if prev is None or et > prev[0]:
                latest[cid] = (et, row["active"])

    active = {cid for cid, (_, a) in latest.items() if a == "1"}
    logger.info(
        "Concepts: %d total IDs, %d active", len(latest), len(active),
    )
    return active


def load_latest_descriptions(
    path: Path,
    active_concepts: set[str],
) -> tuple[dict[str, str], dict[str, str]]:
    """Load FSN and preferred synonym for each concept.

    Returns (fsn_map, synonym_map) where keys are concept IDs.
    For concepts with multiple synonyms, keeps the one from the
    latest-effective row.
    """
    logger.info("Loading descriptions from %s", path)
    # Track latest row per description ID
    latest: dict[str, dict[str, str]] = {}
    with open(path, newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh, delimiter="\t")
        for row in reader:
            did = row["id"]
            prev = latest.get(did)
            if prev is None or row["effectiveTime"] > prev["effectiveTime"]:
                latest[did] = row

    # Build concept-level maps from active descriptions
    fsn_map: dict[str, str] = {}
    synonym_map: dict[str, str] = {}
    for row in latest.values():
        if row["active"] != "1":
            continue
        cid = row["conceptId"]
        if cid not in active_concepts:
            continue
        type_id = row["typeId"]
        term = row["term"]
        if type_id == TYPEID_FSN:
            fsn_map[cid] = term
        elif type_id == TYPEID_SYNONYM:
            # Keep the latest synonym per concept; we already have
            # the latest per description-id, so just overwrite.
            # (Multiple synonyms are fine; we want any one preferred
            # term, and will naturally get the last one iterated.)
            synonym_map[cid] = term

    logger.info(
        "Descriptions: %d FSNs, %d synonyms for %d active concepts",
        len(fsn_map), len(synonym_map), len(active_concepts),
    )
    return fsn_map, synonym_map


def load_latest_definitions(
    path: Path,
    active_concepts: set[str],
) -> dict[str, str]:
    """Load text definitions for concepts.

    Returns {concept_id: definition_text}.
    """
    logger.info("Loading text definitions from %s", path)
    latest: dict[str, dict[str, str]] = {}
    with open(path, newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh, delimiter="\t")
        for row in reader:
            did = row["id"]
            prev = latest.get(did)
            if prev is None or row["effectiveTime"] > prev["effectiveTime"]:
                latest[did] = row

    defn_map: dict[str, str] = {}
    for row in latest.values():
        if row["active"] != "1":
            continue
        cid = row["conceptId"]
        if cid not in active_concepts:
            continue
        defn_map[cid] = row["term"]

    logger.info("Text definitions: %d", len(defn_map))
    return defn_map


def load_latest_relationships(
    path: Path,
    active_concepts: set[str],
    type_ids: set[str],
) -> list[dict[str, str]]:
    """Load active relationships of the specified types.

    Filters to relationships where both source and destination are
    active concepts and the typeId is in the allowed set.

    Returns list of dicts with keys: sourceId, destinationId, typeId.
    """
    logger.info("Loading relationships from %s", path)
    latest: dict[str, dict[str, str]] = {}
    row_count = 0
    with open(path, newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh, delimiter="\t")
        for row in reader:
            row_count += 1
            # Skip relationship types we don't care about early
            if row["typeId"] not in type_ids:
                continue
            rid = row["id"]
            prev = latest.get(rid)
            if prev is None or row["effectiveTime"] > prev["effectiveTime"]:
                latest[rid] = row

    logger.info(
        "Relationships: scanned %d rows, %d latest of target types",
        row_count, len(latest),
    )

    rels: list[dict[str, str]] = []
    for row in latest.values():
        if row["active"] != "1":
            continue
        src = row["sourceId"]
        dst = row["destinationId"]
        if src in active_concepts and dst in active_concepts:
            rels.append({
                "sourceId": src,
                "destinationId": dst,
                "typeId": row["typeId"],
            })

    logger.info("Active relationships of target types: %d", len(rels))
    return rels


# --- Graph traversal ---


def build_isa_tree(
    relationships: list[dict[str, str]],
) -> tuple[dict[str, set[str]], dict[str, set[str]]]:
    """Build IS_A child->parent and parent->child maps.

    IS_A relationships in SNOMED are: sourceId IS_A destinationId
    (child IS_A parent).
    """
    children_of: dict[str, set[str]] = defaultdict(set)  # parent -> children
    parents_of: dict[str, set[str]] = defaultdict(set)    # child -> parents

    for rel in relationships:
        if rel["typeId"] == IS_A_TYPEID:
            child = rel["sourceId"]
            parent = rel["destinationId"]
            children_of[parent].add(child)
            parents_of[child].add(parent)

    return children_of, parents_of


def collect_descendants(
    seeds: list[str],
    children_of: dict[str, set[str]],
) -> set[str]:
    """BFS downward from seeds collecting all descendants (unlimited depth)."""
    visited: set[str] = set(seeds)
    queue: deque[str] = deque(seeds)
    while queue:
        node = queue.popleft()
        for child in children_of.get(node, set()):
            if child not in visited:
                visited.add(child)
                queue.append(child)
    return visited


def collect_ancestors(
    seeds: set[str],
    parents_of: dict[str, set[str]],
    max_levels: int,
) -> set[str]:
    """BFS upward from seeds collecting ancestors up to max_levels."""
    visited: set[str] = set()
    queue: deque[tuple[str, int]] = deque((s, 0) for s in seeds)
    while queue:
        node, depth = queue.popleft()
        if depth >= max_levels:
            continue
        for parent in parents_of.get(node, set()):
            if parent not in visited and parent not in seeds:
                visited.add(parent)
                queue.append((parent, depth + 1))
    return visited


def extract_subgraph(
    seeds: list[str],
    all_relationships: list[dict[str, str]],
    fsn_map: dict[str, str],
) -> tuple[set[str], list[dict[str, str]]]:
    """Extract the hypertension-centered subgraph.

    Strategy:
    1. Walk IS_A descendants from seeds (unlimited depth)
    2. Walk IS_A ancestors from the hierarchy (up to 3 levels)
    3. For each hierarchy concept, follow non-IS_A relationships 1 hop
    4. For body-structure/observable-entity targets, add 1 IS_A parent
    5. Collect all edges within the final concept set
    """
    # Step 1: Build IS_A tree and get descendants
    children_of, parents_of = build_isa_tree(all_relationships)

    hierarchy = collect_descendants(seeds, children_of)
    logger.info(
        "Step 1 — IS_A descendants (hypertension hierarchy): %d concepts",
        len(hierarchy),
    )

    # Step 2: Ancestors up to MAX_ANCESTOR_LEVELS
    ancestors = collect_ancestors(hierarchy, parents_of, MAX_ANCESTOR_LEVELS)
    logger.info(
        "Step 2 — IS_A ancestors (up to %d levels): %d concepts",
        MAX_ANCESTOR_LEVELS, len(ancestors),
    )

    # Step 3: Non-IS_A relationships from hierarchy concepts (1 hop)
    non_isa_rels = [
        r for r in all_relationships if r["typeId"] != IS_A_TYPEID
    ]
    non_isa_targets: set[str] = set()
    for rel in non_isa_rels:
        src, dst = rel["sourceId"], rel["destinationId"]
        if src in hierarchy:
            non_isa_targets.add(dst)
        if dst in hierarchy:
            non_isa_targets.add(src)

    # Remove concepts already in hierarchy or ancestors
    non_isa_targets -= hierarchy
    non_isa_targets -= ancestors
    logger.info(
        "Step 3 — Non-IS_A targets (1 hop from hierarchy): %d new concepts",
        len(non_isa_targets),
    )

    # Step 4: For body-structure and observable-entity targets, add 1 IS_A parent
    taxonomic_parents: set[str] = set()
    for cid in non_isa_targets:
        fsn = fsn_map.get(cid, "")
        tag = extract_semantic_tag(fsn).lower()
        if tag in TAXONOMIC_CONTEXT_TAGS:
            for parent in parents_of.get(cid, set()):
                if (
                    parent not in hierarchy
                    and parent not in ancestors
                    and parent not in non_isa_targets
                ):
                    taxonomic_parents.add(parent)

    logger.info(
        "Step 4 — Taxonomic context parents for body-structure/"
        "observable-entity: %d concepts",
        len(taxonomic_parents),
    )

    # Final concept set
    all_concepts = hierarchy | ancestors | non_isa_targets | taxonomic_parents
    logger.info("Total concepts in subgraph: %d", len(all_concepts))

    # Collect all edges where both endpoints are in the subgraph
    # and the relationship type is one we track
    subgraph_edges: list[dict[str, str]] = []
    for rel in all_relationships:
        src, dst = rel["sourceId"], rel["destinationId"]
        if src in all_concepts and dst in all_concepts:
            subgraph_edges.append(rel)

    logger.info("Total edges in subgraph: %d", len(subgraph_edges))
    return all_concepts, subgraph_edges


# --- Output ---


def write_nodes(
    path: Path,
    concepts: set[str],
    fsn_map: dict[str, str],
    synonym_map: dict[str, str],
    defn_map: dict[str, str],
    edges: list[dict[str, str]],
) -> dict[str, int]:
    """Write nodes.tsv and return entity_type counts.

    Derives entity_type from the FSN semantic tag.  For disorders,
    aggregates finding_sites and associated_morphology from edges.
    """
    # Pre-compute per-concept relationship aggregates
    finding_sites: dict[str, list[str]] = defaultdict(list)
    morphologies: dict[str, list[str]] = defaultdict(list)
    for e in edges:
        type_id = e["typeId"]
        src, dst = e["sourceId"], e["destinationId"]
        if type_id == "363698007":  # Finding site
            name = synonym_map.get(dst, strip_semantic_tag(fsn_map.get(dst, dst)))
            finding_sites[src].append(name)
        elif type_id == "116676008":  # Associated morphology
            name = synonym_map.get(dst, strip_semantic_tag(fsn_map.get(dst, dst)))
            morphologies[src].append(name)

    type_counts: dict[str, int] = defaultdict(int)

    with open(path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh, delimiter="\t")
        writer.writerow(["entity_id", "entity_type", "name", "properties_json"])

        for cid in sorted(concepts):
            fsn = fsn_map.get(cid, "")
            tag = extract_semantic_tag(fsn)
            entity_type = tag_to_entity_type(tag)
            type_counts[entity_type] += 1

            # Preferred name: synonym if available, else FSN without tag
            name = synonym_map.get(cid, strip_semantic_tag(fsn)) or cid

            props = {
                "fsn": fsn,
                "definition": defn_map.get(cid, ""),
                "semantic_tag": tag,
            }
            if tag.lower() == "disorder":
                props["finding_sites"] = sorted(
                    set(finding_sites.get(cid, [])),
                )
                props["associated_morphology"] = sorted(
                    set(morphologies.get(cid, [])),
                )

            writer.writerow([
                cid,
                entity_type,
                name,
                json.dumps(props, ensure_ascii=False),
            ])

    return dict(type_counts)


def write_edges(
    path: Path,
    edges: list[dict[str, str]],
) -> dict[str, int]:
    """Write edges.tsv and return relationship_type counts."""
    type_counts: dict[str, int] = defaultdict(int)

    with open(path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh, delimiter="\t")
        writer.writerow([
            "source_id", "target_id", "relationship_type", "properties_json",
        ])

        for e in edges:
            rel_type = RELATIONSHIP_TYPES.get(e["typeId"], e["typeId"])
            type_counts[rel_type] += 1
            writer.writerow([
                e["sourceId"],
                e["destinationId"],
                rel_type,
                "{}",
            ])

    return dict(type_counts)


# --- Main ---


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--snomed-dir", type=Path, default=None,
        help=(
            "Path to the RF2 Full/Terminology/ directory.  "
            "Auto-detected from retrieval-hub-data-sources/snomed-ct/ "
            "if not specified."
        ),
    )
    parser.add_argument(
        "--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR,
        help="Directory to write subgraph files (default: %(default)s)",
    )
    parser.add_argument(
        "--force", action="store_true",
        help="Overwrite existing output files",
    )
    args = parser.parse_args()

    # Resolve SNOMED directory
    snomed_dir = args.snomed_dir
    if snomed_dir is None:
        snomed_dir = find_snomed_dir(DATA_SOURCES)
        if snomed_dir is None:
            print(
                "Error: could not find SNOMED-CT RF2 directory under "
                f"{DATA_SOURCES / 'snomed-ct'}.  "
                "Use --snomed-dir to specify the path.",
                file=sys.stderr,
            )
            sys.exit(1)
    if not snomed_dir.is_dir():
        print(f"Error: not a directory: {snomed_dir}", file=sys.stderr)
        sys.exit(1)

    logger.info("SNOMED-CT RF2 directory: %s", snomed_dir)

    # Idempotency: skip if output exists
    nodes_out = args.output_dir / "nodes.tsv"
    edges_out = args.output_dir / "edges.tsv"
    if nodes_out.exists() and edges_out.exists() and not args.force:
        logger.info(
            "Output already exists at %s — skipping (use --force to overwrite)",
            args.output_dir,
        )
        return

    # Locate RF2 files
    concept_file = find_rf2_file(snomed_dir, "sct2_Concept_Full")
    desc_file = find_rf2_file(snomed_dir, "sct2_Description_Full")
    defn_file = find_rf2_file(snomed_dir, "sct2_TextDefinition_Full")
    rel_file = find_rf2_file(snomed_dir, "sct2_Relationship_Full")

    for label, f in [
        ("Concept", concept_file),
        ("Description", desc_file),
        ("TextDefinition", defn_file),
        ("Relationship", rel_file),
    ]:
        if f is None:
            print(
                f"Error: {label} file not found in {snomed_dir}",
                file=sys.stderr,
            )
            sys.exit(1)

    # --- Load RF2 data ---

    active_concepts = load_latest_active_concepts(concept_file)

    fsn_map, synonym_map = load_latest_descriptions(desc_file, active_concepts)

    defn_map = load_latest_definitions(defn_file, active_concepts)

    type_ids = set(RELATIONSHIP_TYPES.keys())
    all_relationships = load_latest_relationships(
        rel_file, active_concepts, type_ids,
    )

    # Verify seeds exist
    for seed in SEED_CONCEPTS:
        if seed not in active_concepts:
            print(
                f"Error: seed concept {seed} not found in active concepts",
                file=sys.stderr,
            )
            sys.exit(1)
        logger.info(
            "Seed: %s — %s", seed,
            fsn_map.get(seed, synonym_map.get(seed, "?")),
        )

    # --- Extract subgraph ---

    concepts, edges = extract_subgraph(
        SEED_CONCEPTS, all_relationships, fsn_map,
    )

    # --- Write output ---

    args.output_dir.mkdir(parents=True, exist_ok=True)

    node_type_counts = write_nodes(
        nodes_out, concepts, fsn_map, synonym_map, defn_map, edges,
    )
    edge_type_counts = write_edges(edges_out, edges)

    # --- Summary ---

    total_nodes = sum(node_type_counts.values())
    total_edges = sum(edge_type_counts.values())

    logger.info("Wrote subgraph to %s", args.output_dir)
    logger.info("Nodes: %d", total_nodes)
    for etype, count in sorted(node_type_counts.items(), key=lambda x: -x[1]):
        logger.info("  %s: %d", etype, count)
    logger.info("Edges: %d", total_edges)
    for rtype, count in sorted(edge_type_counts.items(), key=lambda x: -x[1]):
        logger.info("  %s: %d", rtype, count)


if __name__ == "__main__":
    main()
