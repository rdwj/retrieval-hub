"""RewriterService: template-driven, LLM-powered query rewriting."""

from __future__ import annotations

import json
import logging
import re
import uuid
from pathlib import Path
from typing import Any

import yaml

from retrieval_hub.rewriter.llm import LlmClient
from retrieval_hub.rewriter.schemas import RewriteResult, RewrittenQuery
from retrieval_hub.schemas.rewriter import RewriterMetadata
from retrieval_hub.schemas.semantic import SemanticContext

logger = logging.getLogger(__name__)

_FENCE_RE = re.compile(r"```(?:json)?\s*\n?(.*?)\n?\s*```", re.DOTALL)

_DEFAULT_TEMPLATE_PATH = (
    Path(__file__).resolve().parent.parent.parent.parent / "prompts" / "rewriter-shared-core.yaml"
)


class RewriterService:
    """Rewrites user queries using per-source metadata and a shared prompt template.

    Parameters
    ----------
    llm:
        An ``LlmClient`` instance to use for chat-completion calls.
    template_path:
        Path to the YAML prompt template.  Defaults to
        ``prompts/rewriter-shared-core.yaml`` relative to the repo root.
    """

    def __init__(
        self,
        llm: LlmClient,
        template_path: Path | None = None,
    ) -> None:
        self._llm = llm
        self._template_path = template_path or _DEFAULT_TEMPLATE_PATH
        self._template: dict[str, Any] | None = None

    def _load_template(self) -> dict[str, Any]:
        if self._template is not None:
            return self._template

        with open(self._template_path) as fh:
            data: dict[str, Any] = yaml.safe_load(fh)

        for key in ("name", "version", "system", "user"):
            if key not in data:
                msg = f"Prompt template missing required key {key!r}: {self._template_path}"
                raise ValueError(msg)

        self._template = data
        return data

    async def rewrite(
        self,
        query: str,
        metadata: RewriterMetadata,
        *,
        semantic_context: SemanticContext | None = None,
        max_rewrites: int | None = None,
        request_id: str | None = None,
    ) -> RewriteResult:
        """Rewrite *query* using the source's rewriter metadata."""
        effective_max = max_rewrites if max_rewrites is not None else metadata.max_rewrites
        effective_request_id = request_id or str(uuid.uuid4())

        tpl = self._load_template()

        variables = {
            "vocabulary_mappings": _format_vocabulary_mappings(metadata),
            "domain_notes": metadata.domain_notes or "No domain-specific notes provided.",
            "sample_queries": _format_sample_queries(metadata),
            "raw_query": query,
            "max_rewrites": str(effective_max),
            "schema_hints": _format_schema_hints(metadata),
            "entity_definitions": _format_entity_definitions(semantic_context),
            "abbreviations": _format_abbreviations(semantic_context),
            "metric_definitions": _format_metrics(semantic_context),
        }

        system_msg = tpl["system"].format_map(variables)
        user_msg = tpl["user"].format_map(variables)

        logger.info(
            "rewriter.rewrite request_id=%s query=%r max_rewrites=%d",
            effective_request_id,
            query,
            effective_max,
        )

        raw = await self._llm.chat(
            [
                {"role": "system", "content": system_msg},
                {"role": "user", "content": user_msg},
            ],
            temperature=0.0,
        )

        items = _parse_llm_json(raw)
        queries = [RewrittenQuery.model_validate(item) for item in items[:effective_max]]

        return RewriteResult(
            queries=queries,
            raw_query=query,
            template_version=str(tpl["version"]),
            llm=self._llm.model,
            request_id=effective_request_id,
        )


def _format_vocabulary_mappings(metadata: RewriterMetadata) -> str:
    if not metadata.vocabulary_mappings:
        return "No vocabulary mappings provided."

    lines = ["| Lay Term | Canonical Term |", "| --- | --- |"]
    for m in metadata.vocabulary_mappings:
        lines.append(f"| {m.lay_term} | {m.canonical_term} |")
    return "\n".join(lines)


def _format_sample_queries(metadata: RewriterMetadata) -> str:
    if not metadata.sample_queries:
        return "No sample queries provided."

    parts: list[str] = []
    for i, sq in enumerate(metadata.sample_queries, 1):
        part = f"{i}. Raw: {sq.raw!r}"
        if sq.good_rewrites:
            rewrites = "; ".join(repr(r) for r in sq.good_rewrites)
            part += f"\n   Good rewrites: {rewrites}"
        parts.append(part)
    return "\n".join(parts)


def _format_schema_hints(metadata: RewriterMetadata) -> str:
    if not metadata.schema_hints:
        return "No schema hints."
    return json.dumps(metadata.schema_hints, indent=2)


def _format_entity_definitions(semantic: SemanticContext | None) -> str:
    """Render entity definitions as a compact one-line-per-entity list."""
    if not semantic or not semantic.entities:
        return "No entity definitions provided."

    _max_entities = 50

    grouped: dict[str, list] = {}
    for ent in semantic.entities:
        grouped.setdefault(ent.entity_type, []).append(ent)

    lines: list[str] = []
    count = 0
    for etype, entities in grouped.items():
        lines.append(f"**{etype}**")
        for ent in entities:
            if count >= _max_entities:
                lines.append(f"\n({len(semantic.entities) - _max_entities} more entities omitted)")
                return "\n".join(lines)
            first_sentence = ent.definition.split(". ", 1)[0]
            if not first_sentence.endswith("."):
                first_sentence += "."
            alias_part = ""
            if ent.aliases:
                alias_part = f" (also: {', '.join(ent.aliases)})"
            lines.append(f"- {ent.name}{alias_part} ({etype}): {first_sentence}")
            count += 1

    return "\n".join(lines)


def _format_abbreviations(semantic: SemanticContext | None) -> str:
    """Render abbreviations as a compact markdown table."""
    if not semantic or not semantic.abbreviations:
        return "No abbreviations provided."

    _max_abbrevs = 60

    lines = ["| Abbreviation | Expansion |", "| --- | --- |"]
    items = list(semantic.abbreviations.items())
    for abbr, expansion in items[:_max_abbrevs]:
        lines.append(f"| {abbr} | {expansion} |")
    if len(items) > _max_abbrevs:
        lines.append(f"\n({len(items) - _max_abbrevs} more abbreviations omitted)")

    return "\n".join(lines)


def _format_metrics(semantic: SemanticContext | None) -> str:
    """Render metric definitions as a compact list."""
    if not semantic or not semantic.metrics:
        return "No metric definitions provided."

    _max_metrics = 30

    lines: list[str] = []
    for metric in semantic.metrics[:_max_metrics]:
        parts = [f"- {metric.name}: {metric.definition}."]
        if metric.unit:
            parts.append(f" Unit: {metric.unit}.")
        if metric.thresholds:
            threshold_strs = [f"{t.label}={t.value}" for t in metric.thresholds]
            parts.append(f" Thresholds: {', '.join(threshold_strs)}.")
        lines.append("".join(parts))

    if len(semantic.metrics) > _max_metrics:
        lines.append(f"\n({len(semantic.metrics) - _max_metrics} more metrics omitted)")

    return "\n".join(lines)


def _parse_llm_json(raw: str) -> list[dict[str, Any]]:
    """Extract a JSON array from the LLM response, handling code fences."""
    text = raw.strip()

    fence_match = _FENCE_RE.search(text)
    if fence_match:
        text = fence_match.group(1).strip()

    parsed: Any = json.loads(text)

    if isinstance(parsed, dict) and "queries" in parsed:
        parsed = parsed["queries"]

    if not isinstance(parsed, list):
        msg = f"Expected JSON array from LLM, got {type(parsed).__name__}"
        raise ValueError(msg)

    return parsed
