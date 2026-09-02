"""Graph-family adapter with Memgraph-backed refinement.

Extends ``DocumentAdapter`` with a ``graph_traverse_from_seed`` refine
strategy that follows entity relationships in Memgraph to expand
initial vector search hits with graph context.

Retrieve uses pgvector (inherited from DocumentAdapter).  Refine uses
Memgraph via the Bolt protocol.  The bridge between the two backends
is the ``entity_id`` stored as ``doc_title`` on pgvector chunks and as
a node property in Memgraph.
"""

from __future__ import annotations

import logging
import os
from typing import TYPE_CHECKING, Any

import tiktoken

from retrieval_hub.adapters.document import DocumentAdapter, _psycopg_url

if TYPE_CHECKING:
    from retrieval_hub.models import PhysicalIndex, RecipeVersion, Source
    from retrieval_hub.retrieval.api import RefineOutput

logger = logging.getLogger(__name__)

_SUPPORTED_STRATEGIES = frozenset({"graph_traverse_from_seed"})
_DEFAULT_MAX_CONTEXT_TOKENS = 2048
_ENC = tiktoken.get_encoding("cl100k_base")


def _normalize_edge_type(raw: str) -> str:
    """Normalize a human-readable edge type to Memgraph's sanitized form.

    Converts ``" - "`` and ``" > "`` separators to ``"___"`` to match the
    sanitization applied by ``write_graph._sanitize_rel_type()``, which
    replaces every non-alphanumeric, non-underscore character with ``_``.
    """
    return raw.replace(" - ", "___").replace(" > ", "___")


class GraphAdapter(DocumentAdapter):
    """Adapter for graph-family sources with Memgraph-backed refinement."""

    def __init__(
        self,
        *,
        source: Source,
        physical_index: PhysicalIndex,
        recipe_version: RecipeVersion,
        vectors_db_url: str | None = None,
        embedding_endpoint: str | None = None,
        memgraph_bolt_uri: str | None = None,
    ) -> None:
        super().__init__(
            source=source,
            physical_index=physical_index,
            recipe_version=recipe_version,
            vectors_db_url=vectors_db_url,
            embedding_endpoint=embedding_endpoint,
        )
        self._bolt_uri = memgraph_bolt_uri or os.environ.get(
            "MEMGRAPH_BOLT_URI", "bolt://127.0.0.1:7687",
        )
        self._driver = None

    def _get_driver(self):
        if self._driver is None:
            from neo4j import GraphDatabase
            self._driver = GraphDatabase.driver(self._bolt_uri)
        return self._driver

    # -- refine entry point --------------------------------------------------

    def refine(
        self,
        *,
        doc_title: str,
        chunk_index: int,
        query: str,
        window: int,
        request_id: str,
        strategy: str = "graph_traverse_from_seed",
        max_context_tokens: int | None = None,
        min_score: float | None = None,
        edge_types: list[str] | None = None,
        max_nodes: int | None = None,
    ) -> RefineOutput:
        if strategy not in _SUPPORTED_STRATEGIES:
            raise ValueError(
                f"GraphAdapter does not support the '{strategy}' strategy. "
                f"Use 'graph_traverse_from_seed'."
            )
        return self._graph_traverse_refine(
            entity_id=doc_title,
            query=query,
            hops=window if window > 0 else 2,
            request_id=request_id,
            max_context_tokens=max_context_tokens or _DEFAULT_MAX_CONTEXT_TOKENS,
            edge_types=edge_types,
            max_nodes=max_nodes,
        )

    # -- graph traversal -----------------------------------------------------

    def _graph_traverse_refine(
        self,
        *,
        entity_id: str,
        query: str,
        hops: int,
        request_id: str,
        max_context_tokens: int,
        edge_types: list[str] | None = None,
        max_nodes: int | None = None,
    ) -> RefineOutput:
        from retrieval_hub.retrieval.api import RefineOutput

        source_slug = self.source.slug
        driver = self._get_driver()

        normalized_edge_types: list[str] | None = None
        if edge_types is not None:
            normalized_edge_types = [
                _normalize_edge_type(et) for et in edge_types
            ]

        cypher_params: dict[str, Any] = {
            "entity_id": entity_id,
            "slug": source_slug,
        }

        if normalized_edge_types is not None:
            cypher = (
                "MATCH (seed:Entity {entity_id: $entity_id, source_slug: $slug}) "
                f"OPTIONAL MATCH p = (seed)-[*1..{hops}]-(neighbor:Entity) "
                "WHERE neighbor.source_slug = $slug "
                "AND ALL(rel IN relationships(p) WHERE type(rel) IN $edge_types) "
                "WITH seed, neighbor "
                "RETURN DISTINCT "
                "  seed.entity_id AS seed_id, seed.name AS seed_name, "
                "  seed.entity_type AS seed_type, "
                "  neighbor.entity_id AS neighbor_id, "
                "  neighbor.name AS neighbor_name, "
                "  neighbor.entity_type AS neighbor_type"
            )
            cypher_params["edge_types"] = normalized_edge_types
        else:
            cypher = (
                "MATCH (seed:Entity {entity_id: $entity_id, source_slug: $slug}) "
                f"OPTIONAL MATCH (seed)-[r*1..{hops}]-(neighbor:Entity) "
                "WHERE neighbor.source_slug = $slug "
                "WITH seed, neighbor, r "
                "RETURN DISTINCT "
                "  seed.entity_id AS seed_id, seed.name AS seed_name, "
                "  seed.entity_type AS seed_type, "
                "  neighbor.entity_id AS neighbor_id, "
                "  neighbor.name AS neighbor_name, "
                "  neighbor.entity_type AS neighbor_type"
            )

        with driver.session() as session:
            result = session.run(cypher, **cypher_params)
            records = list(result)

        if not records:
            logger.warning(
                "graph.traverse no seed found entity_id=%s slug=%s",
                entity_id, source_slug,
            )
            return RefineOutput(results=[], truncated=False, total_chunks=0)

        seed_record = records[0]
        seed_name = seed_record["seed_name"] or entity_id
        seed_type = seed_record["seed_type"] or "Entity"

        neighbor_ids = []
        for rec in records:
            nid = rec["neighbor_id"]
            if nid and nid != entity_id:
                neighbor_ids.append(nid)

        unique_neighbor_ids = list(dict.fromkeys(neighbor_ids))
        total_neighbors = len(unique_neighbor_ids)

        if max_nodes is not None:
            unique_neighbor_ids = unique_neighbor_ids[:max_nodes]

        rel_records = self._fetch_relationships(
            driver, entity_id, source_slug, hops,
            edge_types=normalized_edge_types,
        )
        context_text = None
        if rel_records:
            context_text = self._render_with_relationships(
                seed_id=entity_id,
                seed_name=seed_name,
                seed_type=seed_type,
                rel_records=rel_records,
                max_tokens=max_context_tokens,
            )

        neighbor_chunks = self._fetch_neighbor_chunks(
            unique_neighbor_ids, request_id,
        )
        logger.info(
            "graph.traverse entity_id=%s hops=%d neighbors=%d chunks=%d",
            entity_id, hops, total_neighbors, len(neighbor_chunks),
        )

        results = neighbor_chunks
        truncated = len(neighbor_chunks) < total_neighbors

        return RefineOutput(
            results=results,
            truncated=truncated,
            total_chunks=total_neighbors,
            context=context_text,
        )

    def _fetch_relationships(
        self,
        driver,
        entity_id: str,
        source_slug: str,
        hops: int,
        *,
        edge_types: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        where_clause = "WHERE neighbor.source_slug = $slug"
        if edge_types is not None:
            where_clause += " AND type(r) IN $edge_types"

        cypher = (
            "MATCH (seed:Entity {entity_id: $entity_id, source_slug: $slug})"
            "-[r]-(neighbor:Entity) "
            f"{where_clause} "
            "RETURN seed.entity_id AS src, type(r) AS rel_type, "
            "  neighbor.entity_id AS tgt, neighbor.name AS tgt_name, "
            "  neighbor.entity_type AS tgt_type, "
            "  startNode(r).entity_id AS edge_src"
        )
        cypher_params: dict[str, Any] = {
            "entity_id": entity_id,
            "slug": source_slug,
        }
        if edge_types is not None:
            cypher_params["edge_types"] = edge_types

        with driver.session() as session:
            result = session.run(cypher, **cypher_params)
            return [dict(rec) for rec in result]

    def _render_with_relationships(
        self,
        *,
        seed_id: str,
        seed_name: str,
        seed_type: str,
        rel_records: list[dict[str, Any]],
        max_tokens: int,
    ) -> str:
        lines = [f"Seed: {seed_name} ({seed_type}, {seed_id})"]
        tokens_used = len(_ENC.encode(lines[0]))

        for rec in rel_records:
            rel_type = rec["rel_type"]
            tgt_name = rec["tgt_name"] or rec["tgt"]
            tgt_type = rec["tgt_type"] or "Entity"
            edge_src = rec.get("edge_src", "")

            if edge_src == seed_id:
                line = f"  --[{rel_type}]--> {tgt_name} ({tgt_type})"
            else:
                line = f"  <--[{rel_type}]-- {tgt_name} ({tgt_type})"

            line_tokens = len(_ENC.encode(line))
            if tokens_used + line_tokens > max_tokens:
                lines.append(f"  ... (truncated at {max_tokens} tokens)")
                break
            lines.append(line)
            tokens_used += line_tokens

        return "\n".join(lines)

    def _fetch_neighbor_chunks(
        self,
        entity_ids: list[str],
        request_id: str,
    ) -> list[Any]:
        from retrieval_hub.retrieval.api import RetrievalResult

        if not entity_ids:
            return []

        import psycopg

        table = self.physical_index.location
        placeholders = ", ".join(["%s"] * len(entity_ids))
        sql = (
            f"SELECT id, chunk_text, chunk_tokens, doc_title, doc_url, "
            f"doc_section, chunk_index "
            f"FROM {table} "
            f"WHERE doc_title IN ({placeholders}) "
            f"ORDER BY chunk_index"
        )

        with psycopg.connect(_psycopg_url(self._vectors_db_url)) as conn:
            with conn.cursor() as cur:
                cur.execute(sql, entity_ids)
                cols = [d.name for d in cur.description]
                rows = [dict(zip(cols, row, strict=True)) for row in cur.fetchall()]

        return [
            RetrievalResult(
                chunk_id=str(row["id"]),
                text=row["chunk_text"],
                score=1.0,
                doc_title=row["doc_title"] or "",
                doc_url=row["doc_url"] or "",
                doc_section=row["doc_section"],
                chunk_index=row["chunk_index"],
                physical_index_id=self.physical_index.id,
                recipe_version=self.recipe_version.version_number,
                request_id=request_id,
            )
            for row in rows
        ]
