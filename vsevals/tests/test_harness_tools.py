"""Tests for vsevals.harness_tools — filesystem and snippet tool functions."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from vsevals.harness_tools import (
    get_snippet_by_key,
    glob_files,
    grep_files,
    read_file,
    search_snippets,
)


# ---------------------------------------------------------------------------
# read_file
# ---------------------------------------------------------------------------


def test_read_file_basic(tmp_repo):
    result = read_file(tmp_repo, "src/main.py")
    assert "def hello():" in result
    assert "1\t" in result  # line numbers


def test_read_file_with_offset(tmp_repo):
    result = read_file(tmp_repo, "src/main.py", offset=1, limit=2)
    # Should skip first line, return 2 lines
    lines = result.strip().split("\n")
    assert len(lines) == 2
    assert "2\t" in lines[0]


def test_read_file_not_found(tmp_repo):
    with pytest.raises(FileNotFoundError, match="not found"):
        read_file(tmp_repo, "nonexistent.py")


def test_read_file_path_traversal(tmp_repo):
    with pytest.raises(PermissionError, match="outside repo root"):
        read_file(tmp_repo, "../../etc/passwd")


def test_read_file_clamps_limit(tmp_repo):
    result = read_file(tmp_repo, "src/main.py", offset=0, limit=99999)
    # Should not crash, limit gets clamped to 2000
    assert result


# ---------------------------------------------------------------------------
# glob_files
# ---------------------------------------------------------------------------


def test_glob_files_py(tmp_repo):
    result = glob_files(tmp_repo, "**/*.py")
    assert "src/main.py" in result
    assert "src/utils.py" in result


def test_glob_files_no_match(tmp_repo):
    result = glob_files(tmp_repo, "**/*.rs")
    assert result == "(no matches)"


def test_glob_files_specific(tmp_repo):
    result = glob_files(tmp_repo, "*.md")
    assert "README.md" in result


# ---------------------------------------------------------------------------
# grep_files
# ---------------------------------------------------------------------------


def test_grep_files_basic(tmp_repo):
    result = grep_files(tmp_repo, "def hello")
    assert "src/main.py" in result
    assert "def hello" in result


def test_grep_files_no_match(tmp_repo):
    result = grep_files(tmp_repo, "nonexistent_function_xyz")
    assert result == "(no matches)"


def test_grep_files_with_path(tmp_repo):
    result = grep_files(tmp_repo, "import", path="src")
    assert "utils.py" in result


def test_grep_files_invalid_regex(tmp_repo):
    with pytest.raises(ValueError, match="invalid regex"):
        grep_files(tmp_repo, "[invalid")


def test_grep_files_path_traversal(tmp_repo):
    with pytest.raises(PermissionError, match="outside repo root"):
        grep_files(tmp_repo, "test", path="../../")


# ---------------------------------------------------------------------------
# search_snippets (mocked HTTP)
# ---------------------------------------------------------------------------


@patch("vsevals.harness_tools.urllib.request.urlopen")
def test_search_snippets_success(mock_urlopen):
    mock_resp = MagicMock()
    mock_resp.read.return_value = b'[{"id": "1", "title": "test"}]'
    mock_resp.__enter__ = MagicMock(return_value=mock_resp)
    mock_resp.__exit__ = MagicMock(return_value=False)
    mock_urlopen.return_value = mock_resp

    result = search_snippets("http://localhost:8000", "test query")
    assert "test" in result


@patch("vsevals.harness_tools.urllib.request.urlopen")
def test_search_snippets_http_error(mock_urlopen):
    import urllib.error
    mock_urlopen.side_effect = urllib.error.HTTPError(
        url="http://test", code=500, msg="Internal Server Error", hdrs={}, fp=None
    )
    with pytest.raises(RuntimeError, match="VoltSnip search failed"):
        search_snippets("http://localhost:8000", "test")


# ---------------------------------------------------------------------------
# get_snippet_by_key (mocked HTTP)
# ---------------------------------------------------------------------------


@patch("vsevals.harness_tools.urllib.request.urlopen")
def test_get_snippet_by_key_success(mock_urlopen):
    mock_resp = MagicMock()
    mock_resp.read.return_value = b'{"id": "1", "code": "x = 1"}'
    mock_resp.__enter__ = MagicMock(return_value=mock_resp)
    mock_resp.__exit__ = MagicMock(return_value=False)
    mock_urlopen.return_value = mock_resp

    result = get_snippet_by_key("http://localhost:8000", "test-key")
    assert "x = 1" in result


@patch("vsevals.harness_tools.urllib.request.urlopen")
def test_get_snippet_by_key_not_found(mock_urlopen):
    import urllib.error
    mock_urlopen.side_effect = urllib.error.HTTPError(
        url="http://test", code=404, msg="Not Found", hdrs={}, fp=None
    )
    with pytest.raises(RuntimeError, match="VoltSnip get_snippet failed"):
        get_snippet_by_key("http://localhost:8000", "missing-key")


# ---------------------------------------------------------------------------
# search_snippets — payload verification
# ---------------------------------------------------------------------------


@patch("vsevals.harness_tools.urllib.request.urlopen")
def test_search_snippets_with_language_and_tags(mock_urlopen):
    """Verify payload includes language and tags when provided."""
    import json

    mock_resp = MagicMock()
    mock_resp.read.return_value = b'[]'
    mock_resp.__enter__ = MagicMock(return_value=mock_resp)
    mock_resp.__exit__ = MagicMock(return_value=False)
    mock_urlopen.return_value = mock_resp

    search_snippets("http://localhost:8000", "query", language="python", tags=["api", "config"])

    # Inspect the Request object passed to urlopen
    req = mock_urlopen.call_args[0][0]
    payload = json.loads(req.data.decode())
    assert payload["language"] == "python"
    assert payload["tags"] == ["api", "config"]
    assert payload["q"] == "query"
    assert payload["limit"] == 5


# ---------------------------------------------------------------------------
# read_file — offset and limit
# ---------------------------------------------------------------------------


def test_read_file_with_offset_and_limit(tmp_repo):
    """Verify offset and limit correctly select line windows."""
    result = read_file(tmp_repo, "src/main.py", offset=2, limit=2)
    lines = result.strip().split("\n")
    assert len(lines) == 2
    # Line numbers start at offset+1 (1-based)
    assert "3\t" in lines[0]
    assert "4\t" in lines[1]


def test_read_file_offset_zero_limit_one(tmp_repo):
    """Read only the first line."""
    result = read_file(tmp_repo, "src/main.py", offset=0, limit=1)
    lines = result.strip().split("\n")
    assert len(lines) == 1
    assert "1\t" in lines[0]


def test_read_file_negative_offset_clamped(tmp_repo):
    """Negative offset is clamped to 0."""
    result = read_file(tmp_repo, "src/main.py", offset=-5, limit=2)
    lines = result.strip().split("\n")
    assert "1\t" in lines[0]


# ---------------------------------------------------------------------------
# grep_files — regex error path
# ---------------------------------------------------------------------------


def test_grep_files_invalid_regex_message(tmp_repo):
    """Ensure the error message includes 'invalid regex'."""
    with pytest.raises(ValueError, match="invalid regex"):
        grep_files(tmp_repo, "(unclosed")
