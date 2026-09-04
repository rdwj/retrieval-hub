"""Tests for doc_section alias resolution via SemanticContext entities."""

from __future__ import annotations

from types import SimpleNamespace

from retrieval_hub.adapters.base import SourceAdapter


def _make_source(semantic_context=None):
    return SimpleNamespace(semantic_context=semantic_context)


class _StubAdapter(SourceAdapter):
    def retrieve(self, *a, **kw):
        raise NotImplementedError

    def refine(self, *a, **kw):
        raise NotImplementedError


def _make_adapter(semantic_context=None):
    """Build a minimal adapter with just the source attribute set."""
    adapter = object.__new__(_StubAdapter)
    adapter.source = _make_source(semantic_context)
    return adapter


class TestExpandDocSection:
    def test_none_passthrough(self):
        adapter = _make_adapter()
        assert adapter._expand_doc_section(None) is None

    def test_no_semantic_context(self):
        adapter = _make_adapter(semantic_context=None)
        result = adapter._expand_doc_section(["Condition"])
        assert result == ["Condition"]

    def test_empty_entities(self):
        adapter = _make_adapter(semantic_context={"entities": []})
        result = adapter._expand_doc_section(["Condition"])
        assert result == ["Condition"]

    def test_exact_name_match_no_expansion(self):
        sc = {"entities": [
            {"name": "Condition", "aliases": ["Disease"]},
        ]}
        adapter = _make_adapter(semantic_context=sc)
        result = adapter._expand_doc_section(["Condition"])
        assert result == ["Condition"]

    def test_alias_expands_to_name(self):
        sc = {"entities": [
            {"name": "Disorder", "aliases": ["Condition", "Disease"]},
        ]}
        adapter = _make_adapter(semantic_context=sc)
        result = adapter._expand_doc_section(["Condition"])
        assert set(result) == {"Condition", "Disorder"}

    def test_case_insensitive_alias_match(self):
        sc = {"entities": [
            {"name": "Disorder", "aliases": ["condition"]},
        ]}
        adapter = _make_adapter(semantic_context=sc)
        result = adapter._expand_doc_section(["Condition"])
        assert set(result) == {"Condition", "Disorder"}

    def test_multiple_aliases_expand(self):
        sc = {"entities": [
            {"name": "Disorder", "aliases": ["Condition", "Disease"]},
            {"name": "Compound", "aliases": ["Drug", "Medication"]},
        ]}
        adapter = _make_adapter(semantic_context=sc)
        result = adapter._expand_doc_section(["Condition", "Drug"])
        assert set(result) == {"Condition", "Disorder", "Drug", "Compound"}

    def test_no_alias_match_returns_original(self):
        sc = {"entities": [
            {"name": "Disorder", "aliases": ["Disease"]},
        ]}
        adapter = _make_adapter(semantic_context=sc)
        result = adapter._expand_doc_section(["Patient"])
        assert result == ["Patient"]

    def test_cross_domain_fhir_to_snomed(self):
        """FHIR 'Condition' should expand to SNOMED 'Disorder'."""
        snomed_sc = {"entities": [
            {"name": "Disorder", "aliases": ["Condition", "Disease"]},
            {"name": "Finding", "aliases": ["Symptom", "Observation"]},
        ]}
        adapter = _make_adapter(semantic_context=snomed_sc)
        result = adapter._expand_doc_section(["Condition"])
        assert "Disorder" in result
        assert "Condition" in result

    def test_cross_domain_hetionet_drug(self):
        """Generic 'Drug' should expand to Hetionet 'Compound'."""
        hetionet_sc = {"entities": [
            {"name": "Compound", "aliases": ["Drug", "Medication"]},
        ]}
        adapter = _make_adapter(semantic_context=hetionet_sc)
        result = adapter._expand_doc_section(["Drug"])
        assert set(result) == {"Drug", "Compound"}
