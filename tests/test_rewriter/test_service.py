"""Tests for RewriterService: template loading, formatting, LLM dispatch, JSON parsing."""

from __future__ import annotations

import json
import textwrap
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
import yaml

from retrieval_hub.rewriter.llm import LlmClient
from retrieval_hub.rewriter.schemas import RewriteResult
from retrieval_hub.rewriter.service import (
    RewriterService,
    _format_abbreviations,
    _format_entity_definitions,
    _format_metrics,
    _format_sample_queries,
    _format_schema_hints,
    _format_vocabulary_mappings,
    _parse_llm_json,
)
from retrieval_hub.schemas.rewriter import (
    RewriterMetadata,
    SampleQueryExample,
    VocabularyMapping,
)
from retrieval_hub.schemas.semantic import (
    EntityDefinition,
    MetricDefinition,
    MetricThreshold,
    SemanticContext,
)

# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------


def _make_metadata(**overrides: object) -> RewriterMetadata:
    defaults: dict = {
        "enabled": True,
        "vocabulary_mappings": [
            VocabularyMapping(
                lay_term="high blood sugar", canonical_term="hyperglycemia"
            ),
            VocabularyMapping(
                lay_term="blood pressure", canonical_term="hypertension"
            ),
        ],
        "domain_notes": "Test domain notes for clinical guidelines.",
        "sample_queries": [
            SampleQueryExample(
                raw="high blood sugar after a meal",
                good_rewrites=["postprandial hyperglycemia management"],
            ),
        ],
        "max_rewrites": 3,
    }
    defaults.update(overrides)
    return RewriterMetadata(**defaults)


def _make_llm_response(
    items: list[dict] | None = None,
) -> str:
    if items is None:
        items = [
            {
                "text": "rewritten query",
                "intent": "test intent",
                "rationale": "test rationale",
                "confidence": 0.9,
            }
        ]
    return json.dumps(items)


def _mock_llm(response: str | None = None) -> AsyncMock:
    llm = AsyncMock(spec=LlmClient)
    llm.model = "test-model"
    llm.chat.return_value = response or _make_llm_response()
    return llm


def _write_template(tmp_path: Path, **overrides: object) -> Path:
    tpl: dict = {
        "name": "test-template",
        "version": "42",
        "system": "System: {vocabulary_mappings} {domain_notes} "
        "{sample_queries} {max_rewrites} {schema_hints} "
        "{entity_definitions} {abbreviations} {metric_definitions}",
        "user": "Query: {raw_query}",
    }
    tpl.update(overrides)
    path = tmp_path / "template.yaml"
    path.write_text(yaml.dump(tpl))
    return path


# ---------------------------------------------------------------------------
# Template loading
# ---------------------------------------------------------------------------


class TestTemplateLoading:
    def test_loads_default_template(self) -> None:
        svc = RewriterService(_mock_llm())
        tpl = svc._load_template()
        assert tpl["name"] == "rewriter-shared-core"
        assert "version" in tpl

    def test_loads_custom_template(self, tmp_path: Path) -> None:
        path = _write_template(tmp_path, name="custom")
        svc = RewriterService(_mock_llm(), template_path=path)
        tpl = svc._load_template()
        assert tpl["name"] == "custom"

    def test_caches_template_on_second_call(self, tmp_path: Path) -> None:
        path = _write_template(tmp_path)
        svc = RewriterService(_mock_llm(), template_path=path)
        first = svc._load_template()
        path.unlink()
        second = svc._load_template()
        assert first is second

    def test_missing_template_raises_file_not_found(self) -> None:
        svc = RewriterService(
            _mock_llm(),
            template_path=Path("/nonexistent/template.yaml"),
        )
        with pytest.raises(FileNotFoundError):
            svc._load_template()

    @pytest.mark.parametrize("missing_key", ["name", "version", "system", "user"])
    def test_template_missing_required_key_raises(
        self, tmp_path: Path, missing_key: str
    ) -> None:
        tpl = {
            "name": "t",
            "version": "1",
            "system": "s",
            "user": "u",
        }
        del tpl[missing_key]
        path = tmp_path / "bad.yaml"
        path.write_text(yaml.dump(tpl))
        svc = RewriterService(_mock_llm(), template_path=path)
        with pytest.raises(ValueError, match=missing_key):
            svc._load_template()


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------


class TestFormatVocabularyMappings:
    def test_produces_markdown_table(self) -> None:
        md = _make_metadata()
        result = _format_vocabulary_mappings(md)
        assert "| Lay Term | Canonical Term |" in result
        assert "| high blood sugar | hyperglycemia |" in result
        assert "| blood pressure | hypertension |" in result

    def test_empty_mappings(self) -> None:
        md = _make_metadata(vocabulary_mappings=[])
        assert _format_vocabulary_mappings(md) == "No vocabulary mappings provided."


class TestFormatSampleQueries:
    def test_produces_numbered_list_with_rewrites(self) -> None:
        md = _make_metadata()
        result = _format_sample_queries(md)
        assert result.startswith("1. Raw: ")
        assert "postprandial hyperglycemia management" in result

    def test_empty_queries(self) -> None:
        md = _make_metadata(sample_queries=[])
        assert _format_sample_queries(md) == "No sample queries provided."

    def test_query_without_good_rewrites(self) -> None:
        md = _make_metadata(
            sample_queries=[SampleQueryExample(raw="plain query")]
        )
        result = _format_sample_queries(md)
        assert "Good rewrites" not in result


class TestFormatSchemaHints:
    def test_renders_json(self) -> None:
        md = _make_metadata(schema_hints={"key": "value"})
        result = _format_schema_hints(md)
        assert '"key": "value"' in result

    def test_no_hints(self) -> None:
        md = _make_metadata(schema_hints=None)
        assert _format_schema_hints(md) == "No schema hints."


# ---------------------------------------------------------------------------
# Semantic context formatting
# ---------------------------------------------------------------------------


def _make_semantic(**overrides: object) -> SemanticContext:
    defaults: dict = {
        "entities": [
            EntityDefinition(
                name="PTSD",
                entity_type="condition",
                definition="Post-traumatic stress disorder. A psychiatric condition.",
                aliases=["shell shock"],
            ),
        ],
        "abbreviations": {"PTSD": "post-traumatic stress disorder", "CBT": "cognitive behavioral therapy"},
        "metrics": [
            MetricDefinition(
                name="PHQ-9",
                metric_type="scoring_cutpoint",
                definition="Depression severity scale.",
                unit="score",
                thresholds=[
                    MetricThreshold(label="mild", value="5-9"),
                    MetricThreshold(label="severe", value="20-27"),
                ],
            ),
        ],
    }
    defaults.update(overrides)
    return SemanticContext(**defaults)


class TestFormatEntityDefinitions:
    def test_renders_entities_with_aliases(self) -> None:
        result = _format_entity_definitions(_make_semantic())
        assert "PTSD" in result
        assert "shell shock" in result
        assert "condition" in result

    def test_none_semantic(self) -> None:
        assert "No entity" in _format_entity_definitions(None)

    def test_empty_entities(self) -> None:
        ctx = _make_semantic(entities=[])
        assert "No entity" in _format_entity_definitions(ctx)

    def test_truncates_definition_to_first_sentence(self) -> None:
        result = _format_entity_definitions(_make_semantic())
        assert "A psychiatric condition" not in result
        assert "Post-traumatic stress disorder." in result


class TestFormatAbbreviations:
    def test_renders_table(self) -> None:
        result = _format_abbreviations(_make_semantic())
        assert "| PTSD |" in result
        assert "| CBT |" in result
        assert "| Abbreviation |" in result

    def test_none_semantic(self) -> None:
        assert "No abbreviation" in _format_abbreviations(None)

    def test_empty_abbreviations(self) -> None:
        ctx = _make_semantic(abbreviations={})
        assert "No abbreviation" in _format_abbreviations(ctx)


class TestFormatMetrics:
    def test_renders_thresholds(self) -> None:
        result = _format_metrics(_make_semantic())
        assert "PHQ-9" in result
        assert "mild=5-9" in result
        assert "severe=20-27" in result

    def test_includes_unit(self) -> None:
        result = _format_metrics(_make_semantic())
        assert "score" in result

    def test_none_semantic(self) -> None:
        assert "No metric" in _format_metrics(None)

    def test_empty_metrics(self) -> None:
        ctx = _make_semantic(metrics=[])
        assert "No metric" in _format_metrics(ctx)


# ---------------------------------------------------------------------------
# JSON parsing (_parse_llm_json)
# ---------------------------------------------------------------------------


class TestParseLlmJson:
    def test_plain_json_array(self) -> None:
        raw = json.dumps([{"text": "q"}])
        assert _parse_llm_json(raw) == [{"text": "q"}]

    def test_json_wrapped_in_code_fence(self) -> None:
        raw = textwrap.dedent("""\
            ```json
            [{"text": "q"}]
            ```""")
        assert _parse_llm_json(raw) == [{"text": "q"}]

    def test_json_wrapped_in_bare_fence(self) -> None:
        raw = textwrap.dedent("""\
            ```
            [{"text": "q"}]
            ```""")
        assert _parse_llm_json(raw) == [{"text": "q"}]

    def test_queries_object_unwrapped(self) -> None:
        raw = json.dumps({"queries": [{"text": "q"}]})
        assert _parse_llm_json(raw) == [{"text": "q"}]

    def test_non_list_raises(self) -> None:
        with pytest.raises(ValueError, match="Expected JSON array"):
            _parse_llm_json(json.dumps({"not_queries": "oops"}))

    def test_invalid_json_raises(self) -> None:
        with pytest.raises(json.JSONDecodeError):
            _parse_llm_json("not json at all")


# ---------------------------------------------------------------------------
# RewriterService.rewrite()
# ---------------------------------------------------------------------------


class TestRewrite:
    @pytest.mark.asyncio
    async def test_calls_llm_with_system_and_user_messages(
        self, tmp_path: Path
    ) -> None:
        llm = _mock_llm()
        tpl_path = _write_template(tmp_path)
        svc = RewriterService(llm, template_path=tpl_path)

        await svc.rewrite("blood sugar", _make_metadata())

        llm.chat.assert_awaited_once()
        messages = llm.chat.call_args.args[0]
        assert len(messages) == 2
        assert messages[0]["role"] == "system"
        assert messages[1]["role"] == "user"
        assert "blood sugar" in messages[1]["content"]

    @pytest.mark.asyncio
    async def test_system_message_contains_vocabulary(
        self, tmp_path: Path
    ) -> None:
        llm = _mock_llm()
        tpl_path = _write_template(tmp_path)
        svc = RewriterService(llm, template_path=tpl_path)

        await svc.rewrite("test", _make_metadata())

        system_msg = llm.chat.call_args.args[0][0]["content"]
        assert "hyperglycemia" in system_msg

    @pytest.mark.asyncio
    async def test_returns_rewrite_result_with_lineage(
        self, tmp_path: Path
    ) -> None:
        llm = _mock_llm()
        tpl_path = _write_template(tmp_path)
        svc = RewriterService(llm, template_path=tpl_path)

        result = await svc.rewrite(
            "test query", _make_metadata(), request_id="req-42"
        )

        assert isinstance(result, RewriteResult)
        assert result.raw_query == "test query"
        assert result.template_version == "42"
        assert result.llm == "test-model"
        assert result.request_id == "req-42"

    @pytest.mark.asyncio
    async def test_generates_request_id_when_not_provided(
        self, tmp_path: Path
    ) -> None:
        svc = RewriterService(_mock_llm(), template_path=_write_template(tmp_path))
        result = await svc.rewrite("q", _make_metadata())
        assert result.request_id
        assert len(result.request_id) > 0

    @pytest.mark.asyncio
    async def test_max_rewrites_parameter_overrides_metadata(
        self, tmp_path: Path
    ) -> None:
        items = [
            {
                "text": f"q{i}",
                "intent": "i",
                "rationale": "r",
                "confidence": 0.9,
            }
            for i in range(5)
        ]
        llm = _mock_llm(json.dumps(items))
        svc = RewriterService(llm, template_path=_write_template(tmp_path))
        md = _make_metadata(max_rewrites=10)

        result = await svc.rewrite("q", md, max_rewrites=2)

        assert len(result.queries) == 2

    @pytest.mark.asyncio
    async def test_metadata_max_rewrites_used_as_default(
        self, tmp_path: Path
    ) -> None:
        items = [
            {
                "text": f"q{i}",
                "intent": "i",
                "rationale": "r",
                "confidence": 0.9,
            }
            for i in range(10)
        ]
        llm = _mock_llm(json.dumps(items))
        svc = RewriterService(llm, template_path=_write_template(tmp_path))
        md = _make_metadata(max_rewrites=3)

        result = await svc.rewrite("q", md)

        assert len(result.queries) == 3

    @pytest.mark.asyncio
    async def test_handles_code_fenced_response(self, tmp_path: Path) -> None:
        fenced = "```json\n" + _make_llm_response() + "\n```"
        llm = _mock_llm(fenced)
        svc = RewriterService(llm, template_path=_write_template(tmp_path))

        result = await svc.rewrite("q", _make_metadata())

        assert len(result.queries) == 1
        assert result.queries[0].text == "rewritten query"

    @pytest.mark.asyncio
    async def test_handles_queries_object_response(
        self, tmp_path: Path
    ) -> None:
        obj = json.dumps(
            {
                "queries": [
                    {
                        "text": "q",
                        "intent": "i",
                        "rationale": "r",
                        "confidence": 0.8,
                    }
                ]
            }
        )
        llm = _mock_llm(obj)
        svc = RewriterService(llm, template_path=_write_template(tmp_path))

        result = await svc.rewrite("q", _make_metadata())

        assert len(result.queries) == 1

    @pytest.mark.asyncio
    async def test_empty_metadata_handled_gracefully(
        self, tmp_path: Path
    ) -> None:
        llm = _mock_llm()
        svc = RewriterService(llm, template_path=_write_template(tmp_path))
        md = _make_metadata(
            vocabulary_mappings=[],
            domain_notes=None,
            sample_queries=[],
            schema_hints=None,
        )

        result = await svc.rewrite("q", md)

        system_msg = llm.chat.call_args.args[0][0]["content"]
        assert "No vocabulary mappings provided." in system_msg
        assert "No sample queries provided." in system_msg
        assert isinstance(result, RewriteResult)

    @pytest.mark.asyncio
    async def test_rewrite_raises_on_llm_error(self, tmp_path: Path) -> None:
        from retrieval_hub.rewriter.llm import LlmError

        llm = _mock_llm()
        llm.chat.side_effect = LlmError("connection refused")
        svc = RewriterService(llm, template_path=_write_template(tmp_path))

        with pytest.raises(LlmError, match="connection refused"):
            await svc.rewrite("q", _make_metadata())

    @pytest.mark.asyncio
    async def test_rewrite_raises_on_invalid_query_schema(
        self, tmp_path: Path
    ) -> None:
        from pydantic import ValidationError

        bad_items = json.dumps([{"text": "q", "intent": "i", "rationale": "r"}])
        llm = _mock_llm(bad_items)
        svc = RewriterService(llm, template_path=_write_template(tmp_path))

        with pytest.raises(ValidationError, match="confidence"):
            await svc.rewrite("q", _make_metadata())
