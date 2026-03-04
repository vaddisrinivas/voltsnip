"""Tests for vsevals.patching — overlay materialization and file patching."""

from __future__ import annotations

from pathlib import Path

import pytest

from vsevals.patching import (
    _ignore_patterns,
    apply_line_range_rewrite,
    apply_rewrite,
    cleanup_overlay,
    materialize_overlay,
)


# ---------------------------------------------------------------------------
# _ignore_patterns
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("names,expected_ignored", [
    ([".git", "src", "main.py"], {".git"}),
    (["__pycache__", "app.py"], {"__pycache__"}),
    (["foo.egg-info", "src"], {"foo.egg-info"}),
    (["node_modules", ".venv", "ok"], {"node_modules", ".venv"}),
    ([".mypy_cache", ".ruff_cache", ".pytest_cache"], {".mypy_cache", ".ruff_cache", ".pytest_cache"}),
    (["src", "tests", "lib"], set()),
])
def test_ignore_patterns(names, expected_ignored):
    result = _ignore_patterns("/repo", names)
    assert result == expected_ignored


# ---------------------------------------------------------------------------
# materialize_overlay
# ---------------------------------------------------------------------------


def test_materialize_overlay(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "src").mkdir()
    (repo / "src" / "main.py").write_text("hello")
    (repo / ".git").mkdir()
    (repo / ".git" / "config").write_text("git config")
    (repo / "__pycache__").mkdir()

    overlay = tmp_path / "overlay"
    materialize_overlay(repo_root=repo, overlay_root=overlay)

    assert (overlay / "src" / "main.py").exists()
    assert (overlay / "src" / "main.py").read_text() == "hello"
    assert not (overlay / ".git").exists()
    assert not (overlay / "__pycache__").exists()


def test_materialize_overlay_replaces_existing(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "file.txt").write_text("content")

    overlay = tmp_path / "overlay"
    overlay.mkdir()
    (overlay / "old.txt").write_text("old")

    materialize_overlay(repo_root=repo, overlay_root=overlay)
    assert (overlay / "file.txt").exists()
    assert not (overlay / "old.txt").exists()


# ---------------------------------------------------------------------------
# apply_rewrite — full file
# ---------------------------------------------------------------------------


def test_apply_rewrite_full_file(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "src").mkdir()
    (repo / "src" / "main.py").write_text("original")

    overlay = tmp_path / "overlay"
    overlay.mkdir()
    (overlay / "src").mkdir()
    (overlay / "src" / "main.py").write_text("original")

    result = apply_rewrite(
        code="new content",
        target_file="src/main.py",
        repo_root=repo,
        overlay_root=overlay,
    )
    assert result.read_text() == "new content"


def test_apply_rewrite_creates_parent_dirs(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    overlay = tmp_path / "overlay"
    overlay.mkdir()

    result = apply_rewrite(
        code="new file",
        target_file="deep/nested/file.py",
        repo_root=repo,
        overlay_root=overlay,
    )
    assert result.exists()
    assert result.read_text() == "new file"


# ---------------------------------------------------------------------------
# apply_rewrite — targeted line range
# ---------------------------------------------------------------------------


def test_apply_rewrite_line_range(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    overlay = tmp_path / "overlay"
    overlay.mkdir()

    original = "line1\nline2\nline3\nline4\nline5\n"
    (overlay / "file.py").write_text(original)
    (repo / "file.py").write_text(original)

    result = apply_rewrite(
        code="replaced2\nreplaced3",
        target_file="file.py",
        repo_root=repo,
        overlay_root=overlay,
        line_start=2,
        line_end=3,
    )
    content = result.read_text()
    assert "line1\n" in content
    assert "replaced2\nreplaced3\n" in content
    assert "line4\n" in content
    assert "line5\n" in content


# ---------------------------------------------------------------------------
# apply_rewrite — target outside repo
# ---------------------------------------------------------------------------


def test_apply_rewrite_outside_repo_raises(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    overlay = tmp_path / "overlay"
    overlay.mkdir()

    with pytest.raises(ValueError, match="not under mount_root"):
        apply_rewrite(
            code="bad",
            target_file="/etc/passwd",
            repo_root=repo,
            overlay_root=overlay,
        )


# ---------------------------------------------------------------------------
# apply_line_range_rewrite (pure function)
# ---------------------------------------------------------------------------


def test_apply_line_range_rewrite_full(tmp_path):
    result = apply_line_range_rewrite(
        code="full replacement",
        original_path=tmp_path / "nonexistent.py",
        line_start=None,
        line_end=None,
    )
    assert result == "full replacement"


def test_apply_line_range_rewrite_targeted(tmp_path):
    original = tmp_path / "file.py"
    original.write_text("a\nb\nc\nd\ne\n")

    result = apply_line_range_rewrite(
        code="B\nC",
        original_path=original,
        line_start=2,
        line_end=3,
    )
    lines = result.split("\n")
    assert lines[0] == "a"
    assert "B" in result
    assert "C" in result
    assert "d" in result


def test_apply_line_range_rewrite_file_not_exists(tmp_path):
    result = apply_line_range_rewrite(
        code="new code",
        original_path=tmp_path / "missing.py",
        line_start=1,
        line_end=5,
    )
    assert result == "new code"


# ---------------------------------------------------------------------------
# cleanup_overlay
# ---------------------------------------------------------------------------


def test_cleanup_overlay(tmp_path):
    overlay = tmp_path / "overlay"
    overlay.mkdir()
    (overlay / "file.txt").write_text("content")
    cleanup_overlay(overlay)
    assert not overlay.exists()


def test_cleanup_overlay_nonexistent(tmp_path):
    cleanup_overlay(tmp_path / "does_not_exist")
