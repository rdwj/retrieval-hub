"""Tests for the generic ingestion pipeline."""

from __future__ import annotations

import json
from pathlib import Path

from retrieval_hub.ingestion.pipeline import (
    _load_bioc_documents,
    _load_code_files,
    _load_documents,
    _make_recipe,
    _make_table_name,
)


class TestLoadDocuments:
    def test_discovers_markdown_files(self, tmp_path: Path):
        (tmp_path / "doc1.md").write_text("# Hello\n\nContent here.")
        (tmp_path / "doc2.md").write_text("# World\n\nMore content.")

        docs = _load_documents(tmp_path)
        assert len(docs) == 2
        titles = {d.title for d in docs}
        assert "doc1" in titles
        assert "doc2" in titles

    def test_discovers_txt_files(self, tmp_path: Path):
        (tmp_path / "notes.txt").write_text("Some plain text notes.")

        docs = _load_documents(tmp_path)
        assert len(docs) == 1
        assert docs[0].content_type == "text/plain"

    def test_discovers_html_files(self, tmp_path: Path):
        (tmp_path / "page.html").write_text("<html><body><h1>Title</h1></body></html>")

        docs = _load_documents(tmp_path)
        assert len(docs) == 1
        assert docs[0].content_type == "text/html"

    def test_skips_readme(self, tmp_path: Path):
        (tmp_path / "README.md").write_text("# README")
        (tmp_path / "doc.md").write_text("# Real doc")

        docs = _load_documents(tmp_path)
        assert len(docs) == 1
        assert docs[0].title == "doc"

    def test_walks_subdirectories(self, tmp_path: Path):
        subdir = tmp_path / "category" / "topic"
        subdir.mkdir(parents=True)
        (subdir / "content.md").write_text("# Content")

        docs = _load_documents(tmp_path)
        assert len(docs) == 1
        assert docs[0].title == "category/topic/content"
        assert docs[0].metadata["category"] == "category"

    def test_empty_directory_returns_empty(self, tmp_path: Path):
        docs = _load_documents(tmp_path)
        assert docs == []

    def test_pdf_files_have_empty_content(self, tmp_path: Path):
        (tmp_path / "manual.pdf").write_bytes(b"%PDF-1.4 fake pdf content")

        docs = _load_documents(tmp_path)
        assert len(docs) == 1
        assert docs[0].content == ""
        assert docs[0].content_type == "application/pdf"
        assert len(docs[0].raw_bytes) > 0


class TestLoadBiocDocuments:
    def test_discovers_json_files(self, tmp_path: Path):
        bioc = {"documents": [{"id": "123", "passages": []}]}
        (tmp_path / "article.json").write_text(json.dumps(bioc))

        results = _load_bioc_documents(tmp_path)
        assert len(results) == 1
        assert results[0][1] == "article"
        assert results[0][0] == bioc

    def test_empty_directory(self, tmp_path: Path):
        results = _load_bioc_documents(tmp_path)
        assert results == []


class TestLoadCodeFiles:
    def test_discovers_python_files(self, tmp_path: Path):
        (tmp_path / "main.py").write_text("def hello(): pass")
        (tmp_path / "utils.py").write_text("def util(): pass")

        files = _load_code_files(tmp_path)
        assert len(files) == 2
        paths = {f[1] for f in files}
        assert "main.py" in paths
        assert "utils.py" in paths

    def test_skips_dunder_files(self, tmp_path: Path):
        (tmp_path / "__init__.py").write_text("")
        (tmp_path / "__main__.py").write_text("")
        (tmp_path / "real.py").write_text("x = 1")

        files = _load_code_files(tmp_path)
        assert len(files) == 1
        assert files[0][1] == "real.py"

    def test_walks_subdirectories(self, tmp_path: Path):
        subdir = tmp_path / "pkg"
        subdir.mkdir()
        (subdir / "module.py").write_text("class Foo: pass")

        files = _load_code_files(tmp_path)
        assert len(files) == 1
        assert files[0][1] == "pkg/module.py"


class TestHelpers:
    def test_make_table_name(self):
        assert _make_table_name("my-source", "v1") == "idx_my_source_v1"
        assert _make_table_name("test", "512_64") == "idx_test_512_64"

    def test_make_recipe(self):
        recipe = _make_recipe(
            family="document",
            chunk_tokens=512,
            overlap_tokens=64,
            embedding_model="nomic-ai/nomic-embed-text-v1.5",
            document_prefix="search_document: ",
            table_name="idx_test_v1",
        )
        assert recipe["chunker"]["chunk_tokens"] == 512
        assert recipe["chunker"]["overlap_tokens"] == 64
        assert recipe["embedding"]["model"] == "nomic-ai/nomic-embed-text-v1.5"
        assert recipe["backend"]["table"] == "idx_test_v1"
