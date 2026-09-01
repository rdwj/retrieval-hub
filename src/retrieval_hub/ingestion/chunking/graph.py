"""Graph data chunker.

Parses graph data files (nodes.tsv + edges.tsv), renders entity
descriptions as natural-language text for embedding, and produces
Chunk objects compatible with the existing ingestion pipeline.

Each graph node becomes one chunk. The rendered text includes the
node's properties and its immediate relationships (up to 10) so the
embedding captures local graph context.  doc_title is set to the
entity_id, which serves as the bridge key back to Memgraph.
"""

from __future__ import annotations

import csv
import json
import logging
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import tiktoken

from retrieval_hub.ingestion.chunking.token_fixed import Chunk

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass
class GraphNode:
    entity_id: str
    entity_type: str
    name: str
    properties: dict[str, Any] = field(default_factory=dict)


@dataclass
class GraphEdge:
    source_id: str
    target_id: str
    relationship_type: str
    properties: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# TSV / SIF parsing
# ---------------------------------------------------------------------------


def parse_graph_nodes(nodes_path: Path) -> list[GraphNode]:
    """Read a TSV with columns: entity_id, entity_type, name, properties_json."""
    nodes: list[GraphNode] = []
    with open(nodes_path, newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh, delimiter="\t")
        for row in reader:
            props_raw = (row.get("properties_json") or "").strip()
            props: dict[str, Any] = {}
            if props_raw:
                try:
                    props = json.loads(props_raw)
                except (json.JSONDecodeError, TypeError):
                    logger.warning(
                        "graph.parse_graph_nodes bad JSON for %s: %s",
                        row.get("entity_id", "?"),
                        props_raw[:120],
                    )
            nodes.append(
                GraphNode(
                    entity_id=row["entity_id"],
                    entity_type=row["entity_type"],
                    name=row["name"],
                    properties=props,
                )
            )
    logger.info("graph.parse_graph_nodes path=%s count=%d", nodes_path, len(nodes))
    return nodes


def parse_graph_edges(edges_path: Path) -> list[GraphEdge]:
    """Read edges from TSV (4 cols) or Hetionet SIF (3 cols).

    TSV columns: source_id, target_id, relationship_type, properties_json
    SIF columns: source_id, relationship_type, target_id  (no properties)

    Format is auto-detected by counting columns in the header row.
    """
    edges: list[GraphEdge] = []
    with open(edges_path, newline="", encoding="utf-8") as fh:
        # Peek at the first line to determine format.
        first_line = fh.readline()
        if not first_line.strip():
            return edges
        col_count = len(first_line.strip().split("\t"))
        fh.seek(0)

        if col_count == 3:
            # Hetionet SIF: source \t metaedge \t target
            reader = csv.reader(fh, delimiter="\t")
            header = next(reader, None)  # skip header
            if header is None:
                return edges
            for row in reader:
                if len(row) < 3:
                    continue
                edges.append(
                    GraphEdge(
                        source_id=row[0],
                        target_id=row[2],
                        relationship_type=row[1],
                    )
                )
        else:
            # Standard 4-column TSV
            reader_dict = csv.DictReader(fh, delimiter="\t")
            for row in reader_dict:
                props_raw = (row.get("properties_json") or "").strip()
                props: dict[str, Any] = {}
                if props_raw:
                    try:
                        props = json.loads(props_raw)
                    except (json.JSONDecodeError, TypeError):
                        logger.warning(
                            "graph.parse_graph_edges bad JSON: %s",
                            props_raw[:120],
                        )
                edges.append(
                    GraphEdge(
                        source_id=row["source_id"],
                        target_id=row["target_id"],
                        relationship_type=row["relationship_type"],
                        properties=props,
                    )
                )

    logger.info("graph.parse_graph_edges path=%s count=%d", edges_path, len(edges))
    return edges


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _prop(node: GraphNode, key: str, default: str = "") -> str:
    """Get a property value as a string, returning *default* if missing."""
    val = node.properties.get(key)
    if val is None or val == "":
        return default
    return str(val)


def _neighbors_by_rel(
    node: GraphNode,
    node_edges: list[GraphEdge],
    all_nodes: dict[str, GraphNode],
    rel_type: str,
    *,
    outbound: bool = True,
    limit: int = 10,
) -> list[str]:
    """Return names of neighbors connected via *rel_type*."""
    names: list[str] = []
    for edge in node_edges:
        if edge.relationship_type != rel_type:
            continue
        if outbound and edge.source_id == node.entity_id:
            peer = all_nodes.get(edge.target_id)
        elif not outbound and edge.target_id == node.entity_id:
            peer = all_nodes.get(edge.source_id)
        else:
            # Accept either direction when the edge touches this node.
            peer_id = (
                edge.target_id
                if edge.source_id == node.entity_id
                else edge.source_id
            )
            peer = all_nodes.get(peer_id)
        if peer:
            names.append(peer.name)
        if len(names) >= limit:
            break
    return names


def _relationship_summary(
    node: GraphNode,
    node_edges: list[GraphEdge],
    all_nodes: dict[str, GraphNode],
    limit: int = 10,
) -> str:
    """One-line summary of a node's immediate relationships."""
    seen = 0
    parts: list[str] = []
    for edge in node_edges:
        if seen >= limit:
            break
        peer_id = (
            edge.target_id
            if edge.source_id == node.entity_id
            else edge.source_id
        )
        peer = all_nodes.get(peer_id)
        peer_name = peer.name if peer else peer_id
        parts.append(f"{edge.relationship_type} -> {peer_name}")
        seen += 1
    return "; ".join(parts)


# ---------------------------------------------------------------------------
# Entity renderers
# ---------------------------------------------------------------------------


def render_fhir_entity(
    node: GraphNode,
    node_edges: list[GraphEdge],
    all_nodes: dict[str, GraphNode],
) -> str:
    """Render a FHIR-sourced entity as natural language."""
    etype = node.entity_type

    if etype == "Patient":
        gender = _prop(node, "gender", "unknown")
        birth = _prop(node, "birthDate", "unknown")
        text = f"Patient: {node.name}. Gender: {gender}. Birth date: {birth}."
        conditions = _neighbors_by_rel(node, node_edges, all_nodes, "HAS_CONDITION")
        meds = _neighbors_by_rel(node, node_edges, all_nodes, "HAS_MEDICATION")
        if conditions:
            text += f" Conditions: {', '.join(conditions)}."
        if meds:
            text += f" Medications: {', '.join(meds)}."
        return text

    if etype == "Condition":
        code = _prop(node, "code", "n/a")
        status = _prop(node, "clinicalStatus", "unknown")
        onset = _prop(node, "onsetDateTime", "unknown")
        return (
            f"Condition: {node.name} (SNOMED: {code}). "
            f"Status: {status}. Onset: {onset}."
        )

    if etype == "MedicationRequest":
        status = _prop(node, "status", "unknown")
        prescribed = _prop(node, "authoredOn", "unknown")
        return (
            f"Medication: {node.name}. "
            f"Status: {status}. Prescribed: {prescribed}."
        )

    if etype == "Observation":
        date = _prop(node, "effectiveDateTime", _prop(node, "issued", "unknown"))
        return f"Observation: {node.name}. Date: {date}."

    if etype == "Encounter":
        start = _prop(node, "periodStart", "unknown")
        end = _prop(node, "periodEnd", "unknown")
        return f"Encounter: {node.name}. Period: {start} to {end}."

    # Fallback for unrecognised FHIR types.
    base = f"Entity ({etype}): {node.name}."
    rel = _relationship_summary(node, node_edges, all_nodes, limit=10)
    if rel:
        base += f" Relationships: {rel}."
    return base


def render_hetionet_entity(
    node: GraphNode,
    node_edges: list[GraphEdge],
    all_nodes: dict[str, GraphNode],
) -> str:
    """Render a Hetionet biomedical knowledge-graph entity."""
    etype = node.entity_type

    if etype == "Disease":
        compounds = _neighbors_by_rel(node, node_edges, all_nodes, "CtD")
        genes = _neighbors_by_rel(node, node_edges, all_nodes, "DaG")
        anatomy = _neighbors_by_rel(node, node_edges, all_nodes, "DlA")
        text = f"Disease: {node.name}."
        if compounds:
            text += f" Treated by: {', '.join(compounds)}."
        if genes:
            text += f" Associated genes: {', '.join(genes)}."
        if anatomy:
            text += f" Affected anatomy: {', '.join(anatomy)}."
        return text

    if etype == "Compound":
        diseases = _neighbors_by_rel(node, node_edges, all_nodes, "CtD")
        genes = _neighbors_by_rel(node, node_edges, all_nodes, "CbG")
        side_effects = _neighbors_by_rel(node, node_edges, all_nodes, "CcSE")
        text = f"Compound: {node.name}."
        if diseases:
            text += f" Treats: {', '.join(diseases)}."
        if genes:
            text += f" Targets: {', '.join(genes)}."
        if side_effects:
            text += f" Side effects: {', '.join(side_effects)}."
        return text

    if etype == "Gene":
        diseases = _neighbors_by_rel(node, node_edges, all_nodes, "DaG")
        processes = _neighbors_by_rel(node, node_edges, all_nodes, "GpBP")
        text = f"Gene: {node.name}."
        if diseases:
            text += f" Associated diseases: {', '.join(diseases)}."
        if processes:
            text += f" Biological processes: {', '.join(processes)}."
        return text

    # Fallback for Anatomy, Biological Process, Side Effect, etc.
    base = f"{etype}: {node.name}."
    rel = _relationship_summary(node, node_edges, all_nodes, limit=10)
    if rel:
        base += f" {rel}."
    return base


def _strict_isa_neighbors(
    node: GraphNode,
    node_edges: list[GraphEdge],
    all_nodes: dict[str, GraphNode],
    *,
    direction: str,
    limit: int = 10,
) -> list[str]:
    """Return names of IS_A neighbors in a strict direction.

    SNOMED IS_A edges: sourceId IS_A destinationId (child IS_A parent).
    direction="parents": edges where this node is the source (outbound).
    direction="children": edges where this node is the destination (inbound).
    """
    names: list[str] = []
    for edge in node_edges:
        if edge.relationship_type != "IS_A":
            continue
        if direction == "parents" and edge.source_id == node.entity_id:
            peer = all_nodes.get(edge.target_id)
        elif direction == "children" and edge.target_id == node.entity_id:
            peer = all_nodes.get(edge.source_id)
        else:
            continue
        if peer:
            names.append(peer.name)
        if len(names) >= limit:
            break
    return names


def render_snomed_entity(
    node: GraphNode,
    node_edges: list[GraphEdge],
    all_nodes: dict[str, GraphNode],
) -> str:
    """Render a SNOMED-CT clinical terminology entity."""
    etype = node.entity_type
    definition = _prop(node, "definition")

    if etype == "Disorder":
        parts = [f"Clinical disorder: {node.name}."]
        if definition:
            parts.append(definition)
        sites = _neighbors_by_rel(node, node_edges, all_nodes, "FINDING_SITE")
        morph = _neighbors_by_rel(
            node, node_edges, all_nodes, "ASSOCIATED_MORPHOLOGY",
        )
        manifestations = _neighbors_by_rel(
            node, node_edges, all_nodes, "HAS_DEFINITIONAL_MANIFESTATION",
        )
        parents = _strict_isa_neighbors(
            node, node_edges, all_nodes, direction="parents",
        )
        children = _strict_isa_neighbors(
            node, node_edges, all_nodes, direction="children",
        )
        if sites:
            parts.append(f"Finding site: {', '.join(sites)}.")
        if morph:
            parts.append(f"Associated morphology: {', '.join(morph)}.")
        if manifestations:
            parts.append(f"Manifestations: {', '.join(manifestations)}.")
        if parents:
            parts.append(f"Parent concepts: {', '.join(parents)}.")
        if children:
            parts.append(f"Subtypes: {', '.join(children)}.")
        return " ".join(parts)

    if etype == "Body Structure":
        parts = [f"Anatomical structure: {node.name}."]
        if definition:
            parts.append(definition)
        parent_structures = _strict_isa_neighbors(
            node, node_edges, all_nodes, direction="parents",
        )
        if parent_structures:
            parts.append(f"Part of: {', '.join(parent_structures)}.")
        return " ".join(parts)

    if etype == "Observable Entity":
        parts = [f"Observable entity: {node.name}."]
        if definition:
            parts.append(definition)
        return " ".join(parts)

    if etype == "Finding":
        parts = [f"Clinical finding: {node.name}."]
        if definition:
            parts.append(definition)
        sites = _neighbors_by_rel(node, node_edges, all_nodes, "FINDING_SITE")
        if sites:
            parts.append(f"Finding site: {', '.join(sites)}.")
        return " ".join(parts)

    if etype == "Qualifier Value":
        parts = [f"Qualifier: {node.name}."]
        if definition:
            parts.append(definition)
        return " ".join(parts)

    if etype == "Procedure":
        parts = [f"Clinical procedure: {node.name}."]
        if definition:
            parts.append(definition)
        sites = _neighbors_by_rel(
            node, node_edges, all_nodes, "PROCEDURE_SITE_DIRECT",
        )
        if sites:
            parts.append(f"Procedure site: {', '.join(sites)}.")
        return " ".join(parts)

    # Fallback for Morphologic Abnormality, Substance, etc.
    base = f"{etype}: {node.name}."
    if definition:
        base += f" {definition}"
    rel = _relationship_summary(node, node_edges, all_nodes, limit=10)
    if rel:
        base += f" Relationships: {rel}."
    return base


def render_default_entity(
    node: GraphNode,
    node_edges: list[GraphEdge],
    all_nodes: dict[str, GraphNode],
) -> str:
    """Domain-agnostic fallback renderer."""
    props_text = ", ".join(
        f"{k}={v}" for k, v in node.properties.items() if v is not None and v != ""
    )
    parts = [f"{node.entity_type}: {node.name}."]
    if props_text:
        parts.append(f"Properties: {props_text}.")

    neighbor_names: list[str] = []
    for edge in node_edges[:10]:
        peer_id = (
            edge.target_id
            if edge.source_id == node.entity_id
            else edge.source_id
        )
        peer = all_nodes.get(peer_id)
        neighbor_names.append(peer.name if peer else peer_id)
    if neighbor_names:
        parts.append(f"Connected to: {', '.join(neighbor_names)}.")

    return " ".join(parts)


# ---------------------------------------------------------------------------
# Renderer registry
# ---------------------------------------------------------------------------

_RENDERERS: dict[str, Callable[..., str]] = {
    "fhir": render_fhir_entity,
    "hetionet": render_hetionet_entity,
    "snomed": render_snomed_entity,
    "default": render_default_entity,
}


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


def chunk_graph_data(
    data_dir: Path,
    *,
    source_slug: str,
    chunk_tokens: int = 512,
    renderer: str = "default",
) -> tuple[list[Chunk], list[GraphNode], list[GraphEdge]]:
    """Parse graph files and produce one Chunk per node.

    Parameters
    ----------
    data_dir:
        Directory containing ``nodes.tsv`` and ``edges.tsv`` (or
        ``edges.sif``).
    source_slug:
        Short identifier for the data source, used in doc_url.
    chunk_tokens:
        Maximum token budget per chunk.
    renderer:
        Which entity renderer to use (``"fhir"``, ``"hetionet"``,
        or ``"default"``).

    Returns
    -------
    (chunks, nodes, edges)
        Chunks ready for embedding, plus the parsed graph structures
        for any downstream graph-loading step.
    """
    # -- Locate files -------------------------------------------------------
    nodes_path = data_dir / "nodes.tsv"
    if not nodes_path.exists():
        raise FileNotFoundError(f"Expected {nodes_path} in data directory")

    edges_path = data_dir / "edges.tsv"
    if not edges_path.exists():
        edges_path = data_dir / "edges.sif"
    if not edges_path.exists():
        raise FileNotFoundError(
            f"Expected edges.tsv or edges.sif in {data_dir}"
        )

    # -- Parse --------------------------------------------------------------
    nodes = parse_graph_nodes(nodes_path)
    edges = parse_graph_edges(edges_path)

    if not nodes:
        logger.warning("graph.chunk_graph_data no nodes found in %s", data_dir)
        return [], nodes, edges

    # -- Build lookups ------------------------------------------------------
    node_lookup: dict[str, GraphNode] = {n.entity_id: n for n in nodes}
    edges_by_node: dict[str, list[GraphEdge]] = defaultdict(list)
    for edge in edges:
        edges_by_node[edge.source_id].append(edge)
        edges_by_node[edge.target_id].append(edge)

    # -- Select renderer ----------------------------------------------------
    render_fn = _RENDERERS.get(renderer)
    if render_fn is None:
        raise ValueError(
            f"Unknown renderer {renderer!r}. "
            f"Available: {', '.join(sorted(_RENDERERS))}"
        )

    # -- Render and chunk ---------------------------------------------------
    encoding = tiktoken.get_encoding("cl100k_base")
    chunks: list[Chunk] = []

    for node in nodes:
        node_edges = edges_by_node.get(node.entity_id, [])
        text = render_fn(node, node_edges, node_lookup)

        tokens = encoding.encode(text)
        if len(tokens) > chunk_tokens:
            # Truncate to budget rather than splitting; entity
            # descriptions should stay as single retrievable units.
            tokens = tokens[:chunk_tokens]
            text = encoding.decode(tokens).strip()

        chunks.append(
            Chunk(
                text=text,
                token_count=len(tokens),
                chunk_index=len(chunks),
                doc_url=f"graph://{source_slug}/{node.entity_id}",
                doc_title=node.entity_id,
                doc_section=node.entity_type,
            )
        )

    logger.info(
        "graph.chunk_graph_data dir=%s renderer=%s nodes=%d edges=%d chunks=%d",
        data_dir,
        renderer,
        len(nodes),
        len(edges),
        len(chunks),
    )
    return chunks, nodes, edges
