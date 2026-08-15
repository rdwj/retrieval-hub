"""Tests for :func:`load_corpus_tree`.

Uses ``tmp_path`` fixtures to build throwaway directory trees with
nested markdown files, verifying recursive discovery, metadata
extraction, skip-stem filtering, and deterministic ordering.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from retrieval_hub.ingestion.fetch import FetchError, load_corpus_tree


def _write(path: Path, content: str = "# placeholder\n") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def test_load_corpus_tree_nested_files(tmp_path: Path) -> None:
    """Recursively finds .md files in subdirectories."""
    _write(tmp_path / "alpha" / "one" / "full-guideline.md", "alpha one content")
    _write(tmp_path / "beta" / "two" / "summary.md", "beta two content")

    docs = load_corpus_tree(tmp_path)

    assert len(docs) == 2
    titles = [d.title for d in docs]
    assert titles == ["alpha/one/full-guideline", "beta/two/summary"]


def test_load_corpus_tree_skips_readme(tmp_path: Path) -> None:
    """README.md (any case) should be filtered out."""
    _write(tmp_path / "catA" / "slug1" / "guide.md")
    _write(tmp_path / "catA" / "slug1" / "README.md")
    _write(tmp_path / "catA" / "slug1" / "readme.md")

    docs = load_corpus_tree(tmp_path)

    assert len(docs) == 1
    assert docs[0].title == "catA/slug1/guide"


def test_load_corpus_tree_skips_all_meta_stems(tmp_path: Path) -> None:
    """INDEX, LICENSE, and CONTRIBUTING should also be skipped."""
    for stem in ("index", "LICENSE", "Contributing"):
        _write(tmp_path / f"{stem}.md")
    _write(tmp_path / "real-content.md")

    docs = load_corpus_tree(tmp_path)

    assert len(docs) == 1
    assert docs[0].title == "real-content"


def test_load_corpus_tree_metadata_extraction(tmp_path: Path) -> None:
    """Metadata should derive category and slug from directory parts."""
    _write(tmp_path / "chronic-disease" / "hypertension" / "full-guideline.md")

    docs = load_corpus_tree(tmp_path)

    assert len(docs) == 1
    meta = docs[0].metadata
    assert meta["category"] == "chronic-disease"
    assert meta["slug"] == "hypertension"
    assert meta["document_type"] == "full-guideline"
    assert meta["source"] == "corpus_tree"


def test_load_corpus_tree_metadata_shallow_path(tmp_path: Path) -> None:
    """A file one level deep gets category but no slug."""
    _write(tmp_path / "overview" / "intro.md")

    docs = load_corpus_tree(tmp_path)

    meta = docs[0].metadata
    assert meta["category"] == "overview"
    assert "slug" not in meta
    assert meta["document_type"] == "intro"


def test_load_corpus_tree_metadata_root_file(tmp_path: Path) -> None:
    """A file at the corpus root has no category or slug."""
    _write(tmp_path / "toplevel.md")

    docs = load_corpus_tree(tmp_path)

    meta = docs[0].metadata
    assert "category" not in meta
    assert "slug" not in meta
    assert meta["document_type"] == "toplevel"


def test_load_corpus_tree_sorted_by_title(tmp_path: Path) -> None:
    """Output should be sorted alphabetically by title."""
    _write(tmp_path / "z-category" / "doc.md")
    _write(tmp_path / "a-category" / "doc.md")
    _write(tmp_path / "m-category" / "doc.md")

    docs = load_corpus_tree(tmp_path)

    titles = [d.title for d in docs]
    assert titles == sorted(titles)


def test_load_corpus_tree_url_and_content_type(tmp_path: Path) -> None:
    """Each doc should have a file:// URL and text/markdown content type."""
    _write(tmp_path / "section" / "page.md", "body text")

    docs = load_corpus_tree(tmp_path)

    assert docs[0].url.startswith("file://")
    assert docs[0].content_type == "text/markdown"
    assert docs[0].content == "body text"


def test_load_corpus_tree_nonexistent_directory() -> None:
    """Should raise FetchError for a missing directory."""
    with pytest.raises(FetchError, match="does not exist"):
        load_corpus_tree(Path("/no/such/dir"))


def test_load_corpus_tree_empty_directory(tmp_path: Path) -> None:
    """An empty directory should return an empty list, not raise."""
    docs = load_corpus_tree(tmp_path)
    assert docs == []
