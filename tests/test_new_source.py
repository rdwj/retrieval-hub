"""Tests for the source scaffolding tool (``scripts/new_source.py``)."""

from __future__ import annotations

import importlib
import importlib.util
import py_compile
import re
import subprocess
import sys
from pathlib import Path
from types import ModuleType

import pytest

# ---------------------------------------------------------------------------
# Import the standalone script as a module
# ---------------------------------------------------------------------------

_SCRIPT_PATH = Path(__file__).resolve().parent.parent / "scripts" / "new_source.py"


def _import_new_source() -> ModuleType:
    spec = importlib.util.spec_from_file_location("new_source", _SCRIPT_PATH)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_mod = _import_new_source()
validate_slug = _mod.validate_slug
VALID_FAMILIES = _mod.VALID_FAMILIES
EXISTING_FAMILY_SCRIPTS = _mod.EXISTING_FAMILY_SCRIPTS


# ---------------------------------------------------------------------------
# Slug validation
# ---------------------------------------------------------------------------


class TestValidateSlug:
    """validate_slug accepts/rejects slugs correctly."""

    @pytest.mark.parametrize(
        "slug",
        [
            "a",
            "ab",
            "my-source",
            "a123",
            "a-b-c",
            "data-source-v2",
            "x0",
            "abc-def-ghi-jkl",
        ],
        ids=lambda s: f"valid:{s}",
    )
    def test_valid_slugs(self, slug: str) -> None:
        ok, err = validate_slug(slug)
        assert ok is True, f"slug {slug!r} should be valid but got: {err}"
        assert err == ""

    @pytest.mark.parametrize(
        ("slug", "fragment"),
        [
            ("", "empty"),
            ("My-Source", "lowercase"),
            ("MY_SOURCE", "lowercase"),
            ("my_source", "lowercase"),
            ("-leading", "start or end"),
            ("trailing-", "start or end"),
            ("a--b", "consecutive"),
            ("has space", "lowercase"),
            ("UPPER", "lowercase"),
            ("under_score", "lowercase"),
        ],
        ids=lambda v: v if isinstance(v, str) else "",
    )
    def test_invalid_slugs(self, slug: str, fragment: str) -> None:
        ok, err = validate_slug(slug)
        assert ok is False, f"slug {slug!r} should be invalid"
        assert fragment in err.lower(), (
            f"error for slug {slug!r} should mention {fragment!r}, got: {err}"
        )


# ---------------------------------------------------------------------------
# Name derivation
# ---------------------------------------------------------------------------


class TestNameDerivation:
    """When --name is omitted the slug is title-cased."""

    @pytest.mark.parametrize(
        ("slug", "expected"),
        [
            ("my-data-source", "My Data Source"),
            ("va-cpg", "Va Cpg"),
            ("simple", "Simple"),
            ("a-b-c", "A B C"),
        ],
    )
    def test_name_from_slug(self, slug: str, expected: str, tmp_path: Path) -> None:
        _run_cli(["--slug", slug, "--output-dir", str(tmp_path)])
        generated = (tmp_path / f"ingest_{slug.replace('-', '_')}.py").read_text()
        assert f'SOURCE_NAME = "{expected}"' in generated

    def test_explicit_name_overrides(self, tmp_path: Path) -> None:
        _run_cli([
            "--slug", "my-src",
            "--name", "Custom Name Here",
            "--output-dir", str(tmp_path),
        ])
        generated = (tmp_path / "ingest_my_src.py").read_text()
        assert 'SOURCE_NAME = "Custom Name Here"' in generated


# ---------------------------------------------------------------------------
# File generation
# ---------------------------------------------------------------------------


class TestFileGeneration:
    """Generated scripts are syntactically valid and contain expected content."""

    def test_output_file_exists(self, tmp_path: Path) -> None:
        _run_cli(["--slug", "test-gen", "--output-dir", str(tmp_path)])
        assert (tmp_path / "ingest_test_gen.py").is_file()

    def test_compiles(self, tmp_path: Path) -> None:
        _run_cli(["--slug", "test-gen", "--output-dir", str(tmp_path)])
        out = tmp_path / "ingest_test_gen.py"
        # py_compile.compile raises on syntax errors when doraise=True
        py_compile.compile(str(out), doraise=True)

    def test_contains_slug(self, tmp_path: Path) -> None:
        _run_cli(["--slug", "test-gen", "--output-dir", str(tmp_path)])
        text = (tmp_path / "ingest_test_gen.py").read_text()
        assert 'SOURCE_SLUG = "test-gen"' in text

    def test_contains_underscored_table(self, tmp_path: Path) -> None:
        _run_cli(["--slug", "test-gen", "--output-dir", str(tmp_path)])
        text = (tmp_path / "ingest_test_gen.py").read_text()
        assert 'PGVECTOR_TABLE = "idx_test_gen_v1"' in text

    def test_contains_expected_imports(self, tmp_path: Path) -> None:
        _run_cli(["--slug", "test-gen", "--output-dir", str(tmp_path)])
        text = (tmp_path / "ingest_test_gen.py").read_text()
        for imp in (
            "from retrieval_hub.db.engine import",
            "from retrieval_hub.ingestion.chunking.token_fixed import",
            "from retrieval_hub.ingestion.embed import",
            "from retrieval_hub.models.enums import SourceFamily",
        ):
            assert imp in text, f"missing import: {imp}"

    def test_no_unreplaced_placeholders(self, tmp_path: Path) -> None:
        """No single braces left from template substitution.

        Python f-strings use single braces, so we only flag lone ``{name}``
        patterns that look like unfilled template variables (lowercase
        identifier, no surrounding braces).
        """
        _run_cli(["--slug", "test-gen", "--output-dir", str(tmp_path)])
        text = (tmp_path / "ingest_test_gen.py").read_text()
        # Match {word} that isn't preceded by { or followed by } (i.e. not
        # a Python dict/set literal or doubled-brace escape).
        leftover = re.findall(r"(?<!\{)\{(slug|slug_underscored|name|family_enum)\}(?!\})", text)
        assert leftover == [], f"unreplaced placeholders: {leftover}"

    def test_help_flag_works(self, tmp_path: Path) -> None:
        _run_cli(["--slug", "test-gen", "--output-dir", str(tmp_path)])
        script = tmp_path / "ingest_test_gen.py"
        result = subprocess.run(
            [sys.executable, str(script), "--help"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        assert result.returncode == 0, result.stderr
        assert "corpus-dir" in result.stdout


# ---------------------------------------------------------------------------
# Family validation
# ---------------------------------------------------------------------------


class TestFamilyValidation:
    """Only document families are accepted; others are rejected."""

    @pytest.mark.parametrize("family", sorted(VALID_FAMILIES))
    def test_valid_families(self, family: str, tmp_path: Path) -> None:
        result = _run_cli(
            ["--slug", "fam-test", "--family", family, "--output-dir", str(tmp_path)],
            check=False,
        )
        assert result.returncode == 0, result.stderr

    @pytest.mark.parametrize("family", sorted(EXISTING_FAMILY_SCRIPTS))
    def test_existing_but_unsupported_families(self, family: str, tmp_path: Path) -> None:
        result = _run_cli(
            ["--slug", "fam-test", "--family", family, "--output-dir", str(tmp_path)],
            check=False,
        )
        assert result.returncode != 0
        assert family in result.stderr

    def test_unknown_family(self, tmp_path: Path) -> None:
        result = _run_cli(
            ["--slug", "fam-test", "--family", "unicorn", "--output-dir", str(tmp_path)],
            check=False,
        )
        assert result.returncode != 0
        assert "unicorn" in result.stderr


# ---------------------------------------------------------------------------
# Overwrite protection
# ---------------------------------------------------------------------------


class TestOverwriteProtection:
    """Existing files are not clobbered unless --force is passed."""

    def test_refuses_without_force(self, tmp_path: Path) -> None:
        _run_cli(["--slug", "ow-test", "--output-dir", str(tmp_path)])
        result = _run_cli(
            ["--slug", "ow-test", "--output-dir", str(tmp_path)],
            check=False,
        )
        assert result.returncode != 0
        assert "already exists" in result.stderr

    def test_force_overwrites(self, tmp_path: Path) -> None:
        _run_cli(["--slug", "ow-test", "--output-dir", str(tmp_path)])
        result = _run_cli(
            ["--slug", "ow-test", "--force", "--output-dir", str(tmp_path)],
            check=False,
        )
        assert result.returncode == 0


# ---------------------------------------------------------------------------
# Output directory
# ---------------------------------------------------------------------------


class TestOutputDirectory:
    """--output-dir controls where the file lands."""

    def test_generates_in_custom_dir(self, tmp_path: Path) -> None:
        out_dir = tmp_path / "custom"
        out_dir.mkdir()
        _run_cli(["--slug", "dir-test", "--output-dir", str(out_dir)])
        assert (out_dir / "ingest_dir_test.py").is_file()

    def test_missing_output_dir_fails(self, tmp_path: Path) -> None:
        result = _run_cli(
            ["--slug", "dir-test", "--output-dir", str(tmp_path / "nope")],
            check=False,
        )
        assert result.returncode != 0
        assert "does not exist" in result.stderr


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _run_cli(
    args: list[str],
    *,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    """Run ``scripts/new_source.py`` as a subprocess and return the result."""
    result = subprocess.run(
        [sys.executable, str(_SCRIPT_PATH), *args],
        capture_output=True,
        text=True,
        timeout=10,
    )
    if check and result.returncode != 0:
        raise AssertionError(
            f"new_source.py exited {result.returncode}\n"
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        )
    return result
