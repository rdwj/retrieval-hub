"""Tests for LLM-based entity discovery."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from retrieval_hub.ontology.discover import (
    _format_chunks,
    _validate_entities,
    sample_chunks,
)


class TestFormatChunks:
    def test_formats_numbered_chunks_with_sections(self) -> None:
        chunks = [
            {"chunk_text": "First chunk text", "doc_section": "Introduction"},
            {"chunk_text": "Second chunk text", "doc_section": "Methods"},
        ]
        result = _format_chunks(chunks)
        assert "Chunk 1 [section: Introduction]" in result
        assert "Chunk 2 [section: Methods]" in result
        assert "First chunk text" in result
        assert "Second chunk text" in result

    def test_handles_missing_section(self) -> None:
        chunks = [{"chunk_text": "text", "doc_section": None}]
        result = _format_chunks(chunks)
        assert "[section: unknown]" in result


class TestValidateEntities:
    def test_valid_entities_pass(self) -> None:
        raw = [
            {
                "name": "Hypertension",
                "entity_type": "condition",
                "definition": "High blood pressure",
                "aliases": ["HTN", "high blood pressure"],
            },
            {
                "name": "SSRIs",
                "entity_type": "drug_class",
                "definition": "Selective serotonin reuptake inhibitors",
                "aliases": [],
            },
        ]
        result = _validate_entities(raw)
        assert len(result) == 2
        assert result[0]["name"] == "Hypertension"
        assert result[0]["aliases"] == ["HTN", "high blood pressure"]

    def test_invalid_entity_skipped(self) -> None:
        raw = [
            {
                "name": "Good",
                "entity_type": "condition",
                "definition": "Valid entity",
            },
            {
                "name": "Bad",
                "extra_field": "not allowed",
                "entity_type": "condition",
                "definition": "Invalid due to extra field",
            },
        ]
        result = _validate_entities(raw)
        assert len(result) == 1
        assert result[0]["name"] == "Good"

    def test_missing_required_field_skipped(self) -> None:
        raw = [{"name": "NoType"}]
        result = _validate_entities(raw)
        assert len(result) == 0

    def test_empty_input(self) -> None:
        assert _validate_entities([]) == []


class TestSampleChunks:
    def _make_conn(self, queries_results: list[list[tuple]]) -> MagicMock:
        """Build a psycopg mock that returns different results per execute call."""
        call_count = 0

        fake_cursor = MagicMock()

        def execute_side_effect(sql, params=None):
            nonlocal call_count
            idx = min(call_count, len(queries_results) - 1)
            call_count += 1
            fake_cursor.fetchall.return_value = queries_results[idx]
            if "DISTINCT doc_section" in sql:
                fake_cursor.description = [MagicMock(name="doc_section")]
                for col in fake_cursor.description:
                    col.name = "doc_section"
            else:
                cols = ["chunk_text", "doc_title", "doc_section", "chunk_index"]
                fake_cursor.description = [MagicMock(name=c) for c in cols]
                for col, name in zip(fake_cursor.description, cols, strict=True):
                    col.name = name

        fake_cursor.execute = MagicMock(side_effect=execute_side_effect)

        fake_conn = MagicMock()
        fake_conn.cursor.return_value.__enter__ = MagicMock(return_value=fake_cursor)
        fake_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)

        fake_ctx = MagicMock()
        fake_ctx.__enter__ = MagicMock(return_value=fake_conn)
        fake_ctx.__exit__ = MagicMock(return_value=False)
        return fake_ctx

    def test_stratified_by_section(self) -> None:
        sections = [("Intro",), ("Methods",)]
        intro_chunks = [
            ("intro text 1", "Doc", "Intro", 0),
            ("intro text 2", "Doc", "Intro", 1),
        ]
        methods_chunks = [
            ("methods text 1", "Doc", "Methods", 5),
        ]
        conn = self._make_conn([sections, intro_chunks, methods_chunks])

        with patch("psycopg.connect", return_value=conn):
            result = sample_chunks("postgresql://fake", "idx_test", per_section=2)

        assert len(result) == 3
        assert result[0]["doc_section"] == "Intro"
        assert result[2]["doc_section"] == "Methods"

    def test_no_sections_fallback(self) -> None:
        no_sections: list[tuple] = []
        fallback_chunks = [
            ("chunk 1", "Doc", None, 0),
            ("chunk 2", "Doc", None, 1),
        ]
        conn = self._make_conn([no_sections, fallback_chunks])

        with patch("psycopg.connect", return_value=conn):
            result = sample_chunks("postgresql://fake", "idx_test")

        assert len(result) == 2
        assert result[0]["chunk_text"] == "chunk 1"
