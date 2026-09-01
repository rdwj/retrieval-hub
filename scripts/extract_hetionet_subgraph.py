#!/usr/bin/env python3
"""Extract a hypertension-centered subgraph from Hetionet.

Reads the full Hetionet v1.0 nodes and edges files, performs a 2-hop BFS
from the hypertension Disease node, and writes the subgraph as nodes.tsv
and edges.tsv formatted for RetrievalHub's graph chunker.

Usage:
    python scripts/extract_hetionet_subgraph.py [--output-dir DIR]
"""

from __future__ import annotations

import argparse
import csv
import logging
import sys
from collections import defaultdict, deque
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(name)s %(levelname)s %(message)s",
)
logger = logging.getLogger(__name__)

HETIONET_DIR = Path(__file__).resolve().parent.parent.parent / (
    "retrieval-hub-data-sources/hetionet/hetnet/tsv"
)
METAEDGE_FILE = Path(__file__).resolve().parent.parent.parent / (
    "retrieval-hub-data-sources/hetionet/describe/edges/metaedges.tsv"
)
DEFAULT_OUTPUT_DIR = Path(__file__).resolve().parent.parent.parent / (
    "retrieval-hub-data-sources/hetionet/hypertension-subgraph"
)

SEED_NAME = "hypertension"


def load_metaedge_map(path: Path) -> dict[str, str]:
    """Build abbreviation -> full name map from metaedges.tsv.

    The file has columns: metaedge, abbreviation, edges, source_nodes,
    target_nodes, unbiased. We map abbreviation -> metaedge (the full
    readable name).
    """
    abbrev_to_full: dict[str, str] = {}
    with open(path, newline="") as fh:
        reader = csv.DictReader(fh, delimiter="\t")
        for row in reader:
            abbrev_to_full[row["abbreviation"]] = row["metaedge"]
    return abbrev_to_full


def load_nodes(path: Path) -> dict[str, dict[str, str]]:
    """Load nodes into {id: {name, kind}} dict."""
    nodes: dict[str, dict[str, str]] = {}
    with open(path, newline="") as fh:
        reader = csv.DictReader(fh, delimiter="\t")
        for row in reader:
            nodes[row["id"]] = {"name": row["name"], "kind": row["kind"]}
    return nodes


def load_adjacency(
    path: Path,
) -> tuple[list[tuple[str, str, str]], dict[str, set[str]]]:
    """Load edges and build an undirected adjacency list.

    Returns (edges_list, adjacency) where:
    - edges_list: [(source, metaedge, target), ...]
    - adjacency: {node_id: {neighbor_id, ...}}
    """
    edges: list[tuple[str, str, str]] = []
    adj: dict[str, set[str]] = defaultdict(set)
    with open(path, newline="") as fh:
        reader = csv.DictReader(fh, delimiter="\t")
        for row in reader:
            src, meta, tgt = row["source"], row["metaedge"], row["target"]
            edges.append((src, meta, tgt))
            adj[src].add(tgt)
            adj[tgt].add(src)
    return edges, adj


def find_seed_node(
    nodes: dict[str, dict[str, str]], name: str,
) -> str | None:
    """Find a node by case-insensitive partial name match.

    Prefers exact matches; falls back to partial.
    """
    name_lower = name.lower()
    # Exact match first
    for nid, attrs in nodes.items():
        if attrs["name"].lower() == name_lower:
            return nid
    # Partial match
    for nid, attrs in nodes.items():
        if name_lower in attrs["name"].lower():
            return nid
    return None


def bfs(
    seed: str, adjacency: dict[str, set[str]], max_hops: int,
) -> set[str]:
    """BFS from seed up to max_hops, returning all reachable node IDs."""
    visited: set[str] = {seed}
    queue: deque[tuple[str, int]] = deque([(seed, 0)])
    while queue:
        node, depth = queue.popleft()
        if depth >= max_hops:
            continue
        for neighbor in adjacency.get(node, set()):
            if neighbor not in visited:
                visited.add(neighbor)
                queue.append((neighbor, depth + 1))
    return visited


def write_subgraph(
    output_dir: Path,
    reachable: set[str],
    all_nodes: dict[str, dict[str, str]],
    all_edges: list[tuple[str, str, str]],
    metaedge_map: dict[str, str],
) -> tuple[int, int]:
    """Write filtered nodes.tsv and edges.tsv for the graph chunker.

    Returns (node_count, edge_count).
    """
    output_dir.mkdir(parents=True, exist_ok=True)

    # Write nodes
    nodes_path = output_dir / "nodes.tsv"
    node_count = 0
    with open(nodes_path, "w", newline="") as fh:
        writer = csv.writer(fh, delimiter="\t")
        writer.writerow(["entity_id", "entity_type", "name", "properties_json"])
        for nid in sorted(reachable):
            attrs = all_nodes[nid]
            writer.writerow([nid, attrs["kind"], attrs["name"], "{}"])
            node_count += 1

    # Write edges (only edges where both endpoints are in the subgraph)
    edges_path = output_dir / "edges.tsv"
    edge_count = 0
    with open(edges_path, "w", newline="") as fh:
        writer = csv.writer(fh, delimiter="\t")
        writer.writerow([
            "source_id", "target_id", "relationship_type", "properties_json",
        ])
        for src, meta, tgt in all_edges:
            if src in reachable and tgt in reachable:
                rel_type = metaedge_map.get(meta, meta)
                writer.writerow([src, tgt, rel_type, "{}"])
                edge_count += 1

    return node_count, edge_count


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR,
        help="Directory to write subgraph files (default: %(default)s)",
    )
    parser.add_argument(
        "--hops", type=int, default=2,
        help="BFS hop depth from seed node (default: %(default)s)",
    )
    parser.add_argument(
        "--seed", default=SEED_NAME,
        help="Seed node name to search for (default: %(default)s)",
    )
    parser.add_argument(
        "--force", action="store_true",
        help="Overwrite existing output files",
    )
    args = parser.parse_args()

    # Idempotency: skip if output already exists
    nodes_out = args.output_dir / "nodes.tsv"
    edges_out = args.output_dir / "edges.tsv"
    if nodes_out.exists() and edges_out.exists() and not args.force:
        logger.info(
            "Output already exists at %s — skipping (use --force to overwrite)",
            args.output_dir,
        )
        return

    # Validate input files
    nodes_file = HETIONET_DIR / "hetionet-v1.0-nodes.tsv"
    edges_file = HETIONET_DIR / "hetionet-v1.0-edges.sif"
    for f in (nodes_file, edges_file, METAEDGE_FILE):
        if not f.exists():
            print(f"Error: required file not found: {f}", file=sys.stderr)
            sys.exit(1)

    # Load metaedge abbreviation -> full name mapping
    logger.info("Loading metaedge definitions from %s", METAEDGE_FILE)
    metaedge_map = load_metaedge_map(METAEDGE_FILE)
    logger.info("Loaded %d metaedge definitions", len(metaedge_map))

    # Load nodes
    logger.info("Loading nodes from %s", nodes_file)
    all_nodes = load_nodes(nodes_file)
    logger.info("Loaded %d nodes", len(all_nodes))

    # Find seed
    seed_id = find_seed_node(all_nodes, args.seed)
    if seed_id is None:
        print(
            f"Error: no node matching '{args.seed}' found", file=sys.stderr,
        )
        sys.exit(1)
    logger.info(
        "Seed node: %s (%s)", seed_id, all_nodes[seed_id]["name"],
    )

    # Load edges + adjacency
    logger.info("Loading edges from %s", edges_file)
    all_edges, adjacency = load_adjacency(edges_file)
    logger.info("Loaded %d edges", len(all_edges))

    # BFS
    logger.info("Running %d-hop BFS from %s", args.hops, seed_id)
    reachable = bfs(seed_id, adjacency, args.hops)
    logger.info("Reachable nodes: %d", len(reachable))

    # Collect entity type breakdown
    type_counts: dict[str, int] = defaultdict(int)
    for nid in reachable:
        type_counts[all_nodes[nid]["kind"]] += 1

    # Write output
    node_count, edge_count = write_subgraph(
        args.output_dir, reachable, all_nodes, all_edges, metaedge_map,
    )

    logger.info("Wrote subgraph to %s", args.output_dir)
    logger.info("  Nodes: %d", node_count)
    logger.info("  Edges: %d", edge_count)
    logger.info("  Entity types:")
    for kind, count in sorted(type_counts.items(), key=lambda x: -x[1]):
        logger.info("    %s: %d", kind, count)


if __name__ == "__main__":
    main()
