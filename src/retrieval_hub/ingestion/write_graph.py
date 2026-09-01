"""Write graph structure (nodes and edges) to Memgraph via the Bolt protocol.

Uses the neo4j Python driver in sync mode. Nodes are MERGE'd by
(entity_id, source_slug) for idempotency, so re-running ingestion is safe.
Edge relationship types are sanitized and written per-type since Cypher does
not support parameterized relationship types.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from itertools import islice

from retrieval_hub.ingestion.chunking.graph import GraphEdge, GraphNode

logger = logging.getLogger(__name__)

BATCH_SIZE = 500


@dataclass
class GraphWriteStats:
    nodes_written: int
    edges_written: int
    source_slug: str


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_SAFE_REL_RE = re.compile(r"[^A-Za-z0-9_]")


def _sanitize_rel_type(raw: str) -> str:
    """Replace non-alphanumeric/underscore characters with underscores."""
    sanitized = _SAFE_REL_RE.sub("_", raw)
    # Ensure it doesn't start with a digit (invalid Cypher identifier)
    if sanitized and sanitized[0].isdigit():
        sanitized = "_" + sanitized
    return sanitized or "RELATED_TO"


def _batched(iterable, n: int):
    """Yield successive n-sized chunks from an iterable."""
    it = iter(iterable)
    while True:
        batch = list(islice(it, n))
        if not batch:
            return
        yield batch


def _group_edges_by_type(
    edges: list[GraphEdge],
) -> dict[str, list[GraphEdge]]:
    """Group edges by their sanitized relationship type."""
    groups: dict[str, list[GraphEdge]] = {}
    for edge in edges:
        rel_type = _sanitize_rel_type(edge.relationship_type)
        groups.setdefault(rel_type, []).append(edge)
    return groups


# ---------------------------------------------------------------------------
# Index management
# ---------------------------------------------------------------------------


def ensure_graph_indexes(bolt_uri: str) -> None:
    """Create Memgraph indexes idempotently.

    Memgraph uses ``CREATE INDEX ON :Label(property)`` syntax (not the
    Neo4j ``CREATE INDEX name FOR ...`` form).
    """
    import neo4j

    driver = neo4j.GraphDatabase.driver(bolt_uri)
    try:
        with driver.session() as session:
            session.run("CREATE INDEX ON :Entity(entity_id);")
            session.run("CREATE INDEX ON :Entity(source_slug);")
        logger.info("write_graph.ensure_graph_indexes ok")
    finally:
        driver.close()


# ---------------------------------------------------------------------------
# Core write
# ---------------------------------------------------------------------------


def write_graph_structure(
    bolt_uri: str,
    nodes: list[GraphNode],
    edges: list[GraphEdge],
    source_slug: str,
) -> GraphWriteStats:
    """Write nodes and edges to Memgraph. Returns a stats summary.

    Nodes are MERGE'd on (entity_id, source_slug) so repeated runs are
    idempotent. Properties are stored as a JSON string because Memgraph
    node properties must be primitive types.
    """
    import neo4j

    driver = neo4j.GraphDatabase.driver(bolt_uri)
    try:
        # Indexes first (idempotent)
        with driver.session() as session:
            session.run("CREATE INDEX ON :Entity(entity_id);")
            session.run("CREATE INDEX ON :Entity(source_slug);")

        # -- Nodes --
        nodes_written = 0
        for batch_num, batch in enumerate(_batched(nodes, BATCH_SIZE), 1):
            params = [
                {
                    "entity_id": n.entity_id,
                    "source_slug": source_slug,
                    "name": n.name,
                    "entity_type": n.entity_type,
                    "properties_json": json.dumps(
                        n.properties, default=str
                    ),
                }
                for n in batch
            ]
            with driver.session() as session:
                session.run(
                    """
                    UNWIND $batch AS row
                    MERGE (n:Entity {
                        entity_id: row.entity_id,
                        source_slug: row.source_slug
                    })
                    SET n.name = row.name,
                        n.entity_type = row.entity_type,
                        n.properties_json = row.properties_json
                    """,
                    batch=params,
                )
            nodes_written += len(batch)
            logger.info(
                "write_graph.nodes batch=%d wrote=%d cumulative=%d",
                batch_num,
                len(batch),
                nodes_written,
            )

        # -- Edges --
        edges_written = 0
        grouped = _group_edges_by_type(edges)
        for rel_type, rel_edges in grouped.items():
            for batch_num, batch in enumerate(
                _batched(rel_edges, BATCH_SIZE), 1
            ):
                edge_params = [
                    {
                        "source_id": e.source_id,
                        "target_id": e.target_id,
                        "properties_json": json.dumps(
                            e.properties, default=str
                        ),
                    }
                    for e in batch
                ]
                # Relationship type is baked into the query string because
                # Cypher does not support parameterized relationship types.
                # Safe: rel_type is sanitized by _sanitize_rel_type.
                query = f"""
                    UNWIND $edges AS e
                    MATCH (a:Entity {{
                        entity_id: e.source_id,
                        source_slug: $slug
                    }})
                    MATCH (b:Entity {{
                        entity_id: e.target_id,
                        source_slug: $slug
                    }})
                    MERGE (a)-[r:{rel_type}]->(b)
                    SET r.properties_json = e.properties_json
                """
                with driver.session() as session:
                    session.run(query, edges=edge_params, slug=source_slug)
                edges_written += len(batch)
                logger.info(
                    "write_graph.edges rel=%s batch=%d wrote=%d cumulative=%d",
                    rel_type,
                    batch_num,
                    len(batch),
                    edges_written,
                )
    finally:
        driver.close()

    logger.info(
        "write_graph.write_graph_structure source=%s nodes=%d edges=%d",
        source_slug,
        nodes_written,
        edges_written,
    )
    return GraphWriteStats(
        nodes_written=nodes_written,
        edges_written=edges_written,
        source_slug=source_slug,
    )


# ---------------------------------------------------------------------------
# Source cleanup
# ---------------------------------------------------------------------------


def clear_graph_source(bolt_uri: str, source_slug: str) -> int:
    """Delete all nodes and edges for a source. Returns deleted node count.

    Uses DETACH DELETE so edges are removed alongside nodes.
    """
    import neo4j

    driver = neo4j.GraphDatabase.driver(bolt_uri)
    try:
        with driver.session() as session:
            result = session.run(
                """
                MATCH (n:Entity {source_slug: $source_slug})
                DETACH DELETE n
                RETURN count(n) AS deleted
                """,
                source_slug=source_slug,
            )
            record = result.single()
            deleted = record["deleted"] if record else 0
    finally:
        driver.close()

    logger.info(
        "write_graph.clear_graph_source source=%s deleted=%d",
        source_slug,
        deleted,
    )
    return deleted
