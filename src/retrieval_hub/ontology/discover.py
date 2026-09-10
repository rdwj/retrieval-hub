"""LLM-based entity discovery for new data sources.

Samples chunks from a pgvector index table, sends them to an LLM, and
returns validated ``EntityDefinition`` dicts suitable for storing on
``Source.semantic_context``.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_PROMPT_PATH = Path(__file__).resolve().parents[3] / "prompts" / "entity-discovery.yaml"
_MAX_SAMPLE_CHUNKS = 30
_CHUNKS_PER_SECTION = 3
_MAX_RETRIES = 3


def _load_prompt() -> dict[str, str]:
    """Load the entity-discovery YAML prompt template."""
    import yaml

    text = _PROMPT_PATH.read_text(encoding="utf-8")
    return yaml.safe_load(text)


def _psycopg_url(sqla_url: str) -> str:
    if sqla_url.startswith("postgresql+psycopg://"):
        return "postgresql://" + sqla_url[len("postgresql+psycopg://"):]
    if sqla_url.startswith("postgres+psycopg://"):
        return "postgresql://" + sqla_url[len("postgres+psycopg://"):]
    return sqla_url


def sample_chunks(
    vectors_db_url: str,
    table: str,
    *,
    max_chunks: int = _MAX_SAMPLE_CHUNKS,
    per_section: int = _CHUNKS_PER_SECTION,
) -> list[dict[str, Any]]:
    """Sample representative chunks from a pgvector index table.

    Uses stratified sampling by ``doc_section``: picks the first
    ``per_section`` chunks from each section (early chunks tend to be
    definitional). Falls back to the first ``max_chunks`` rows by
    ``chunk_index`` if no sections exist.
    """
    import psycopg

    with psycopg.connect(_psycopg_url(vectors_db_url)) as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"SELECT DISTINCT doc_section FROM {table} "
                f"WHERE doc_section IS NOT NULL ORDER BY doc_section"
            )
            sections = [row[0] for row in cur.fetchall()]

            if sections:
                sampled: list[dict[str, Any]] = []
                for section in sections:
                    cur.execute(
                        f"SELECT chunk_text, doc_title, doc_section, chunk_index "
                        f"FROM {table} "
                        f"WHERE doc_section = %s "
                        f"ORDER BY chunk_index "
                        f"LIMIT %s",
                        (section, per_section),
                    )
                    cols = [d.name for d in cur.description or []]
                    for row in cur.fetchall():
                        sampled.append(dict(zip(cols, row, strict=True)))
                        if len(sampled) >= max_chunks:
                            break
                    if len(sampled) >= max_chunks:
                        break
                return sampled

            cur.execute(
                f"SELECT chunk_text, doc_title, doc_section, chunk_index "
                f"FROM {table} ORDER BY chunk_index LIMIT %s",
                (max_chunks,),
            )
            cols = [d.name for d in cur.description or []]
            return [dict(zip(cols, row, strict=True)) for row in cur.fetchall()]


def _format_chunks(chunks: list[dict[str, Any]]) -> str:
    parts = []
    for i, chunk in enumerate(chunks, 1):
        section = chunk.get("doc_section") or "unknown"
        parts.append(f"--- Chunk {i} [section: {section}] ---\n{chunk['chunk_text']}")
    return "\n\n".join(parts)


def _get_existing_concepts(db_url: str) -> list[str]:
    """Fetch all canonical concept names from the ontology registry."""
    import psycopg

    with psycopg.connect(_psycopg_url(db_url)) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT DISTINCT name FROM ontology_concept ORDER BY name")
            return [row[0] for row in cur.fetchall()]


def _call_llm(
    llm_url: str,
    llm_model: str,
    system_prompt: str,
    user_prompt: str,
) -> list[dict[str, Any]]:
    """Call the LLM and parse the entity definitions from its response."""
    import httpx
    from openai import OpenAI

    client = OpenAI(
        api_key="local",
        base_url=llm_url if llm_url.endswith("/v1") else f"{llm_url}/v1",
        http_client=httpx.Client(timeout=300.0),
    )

    for attempt in range(_MAX_RETRIES):
        try:
            stream = client.chat.completions.create(
                model=llm_model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=0.3,
                max_tokens=4096,
                extra_body={"chat_template_kwargs": {"enable_thinking": False}},
                response_format={"type": "json_object"},
                stream=True,
            )
            parts = []
            for chunk in stream:
                if chunk.choices and chunk.choices[0].delta.content:
                    parts.append(chunk.choices[0].delta.content)
            content = "".join(parts)
            parsed = json.loads(content)

            entities = parsed.get("entities", [])
            if not entities:
                logger.warning("LLM attempt %d: no entities in response", attempt + 1)
                continue
            return entities

        except Exception:
            logger.warning(
                "LLM attempt %d failed", attempt + 1, exc_info=True,
            )

    logger.error("Entity discovery failed after %d attempts", _MAX_RETRIES)
    return []


def _validate_entities(raw: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Validate raw LLM output against the EntityDefinition schema."""
    from retrieval_hub.schemas.semantic import EntityDefinition

    valid = []
    for item in raw:
        try:
            ed = EntityDefinition.model_validate(item)
            valid.append(ed.model_dump())
        except Exception:
            logger.warning(
                "Skipping invalid entity: %s", item.get("name", "<unknown>"),
                exc_info=True,
            )
    return valid


def discover_entities(
    *,
    vectors_db_url: str,
    table: str,
    db_url: str,
    source_name: str,
    source_family: str,
    source_description: str,
    llm_url: str,
    llm_model: str = "/mnt/models",
) -> list[dict[str, Any]]:
    """Sample chunks, call LLM, return validated entity definitions.

    Returns an empty list if the LLM call fails or produces no valid
    entities. Callers should check the length before updating the source.
    """
    chunks = sample_chunks(vectors_db_url, table)
    if not chunks:
        logger.warning("No chunks found in %s, skipping entity discovery", table)
        return []

    logger.info(
        "discover_entities: sampled %d chunks from %s", len(chunks), table,
    )

    existing_concepts = _get_existing_concepts(db_url)
    concept_list = ", ".join(existing_concepts) if existing_concepts else "(none yet)"

    prompt_template = _load_prompt()
    system_prompt = prompt_template["system"].format(
        existing_concepts=concept_list,
    )
    user_prompt = prompt_template["user"].format(
        source_name=source_name,
        source_family=source_family,
        source_description=source_description,
        chunk_count=len(chunks),
        chunk_texts=_format_chunks(chunks),
    )

    raw_entities = _call_llm(llm_url, llm_model, system_prompt, user_prompt)
    if not raw_entities:
        return []

    valid = _validate_entities(raw_entities)
    logger.info(
        "discover_entities: %d/%d entities validated for %s",
        len(valid), len(raw_entities), table,
    )
    return valid
