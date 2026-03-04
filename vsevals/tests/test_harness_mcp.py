"""Tests for vsevals.harness_mcp — MCP server and tool routing."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from vsevals.harness_mcp import (
    HarnessMCPServer,
    _TOOLS,
    _FS_TOOL_NAMES,
    _call_tool,
)


# ---------------------------------------------------------------------------
# _call_tool routing
# ---------------------------------------------------------------------------


def test_call_tool_read_file(tmp_repo):
    result = _call_tool(tmp_repo, "http://localhost:8000", "read_file", {"path": "src/main.py"})
    assert "def hello" in result


def test_call_tool_glob_files(tmp_repo):
    result = _call_tool(tmp_repo, "http://localhost:8000", "glob_files", {"pattern": "**/*.py"})
    assert "main.py" in result


def test_call_tool_grep_files(tmp_repo):
    result = _call_tool(tmp_repo, "http://localhost:8000", "grep_files", {"pattern": "def hello"})
    assert "main.py" in result


@patch("vsevals.harness_mcp.search_snippets", return_value="search result")
def test_call_tool_search_memory(mock_search, tmp_repo):
    result = _call_tool(tmp_repo, "http://localhost:8000", "search_memory", {"query": "test"})
    assert result == "search result"
    mock_search.assert_called_once()


@patch("vsevals.harness_mcp.search_snippets", return_value="search result")
def test_call_tool_search_snippets(mock_search, tmp_repo):
    result = _call_tool(tmp_repo, "http://localhost:8000", "search_snippets", {"intent": "test"})
    assert result == "search result"


@patch("vsevals.harness_mcp.get_snippet_by_key", return_value='{"code": "x"}')
def test_call_tool_get_snippet_by_canonical_key(mock_get, tmp_repo):
    result = _call_tool(tmp_repo, "http://localhost:8000", "get_snippet_by_canonical_key", {"key": "k1"})
    assert "x" in result


@patch("vsevals.harness_mcp.get_snippet_by_key", return_value='{"code": "x"}')
def test_call_tool_get_snippet_by_key(mock_get, tmp_repo):
    result = _call_tool(tmp_repo, "http://localhost:8000", "get_snippet_by_key", {"key": "k1"})
    assert "x" in result


def test_call_tool_unknown():
    with pytest.raises(ValueError, match="unknown tool"):
        _call_tool(Path("/tmp"), "http://localhost:8000", "nonexistent_tool", {})


@patch("vsevals.harness_mcp.get_snippet_by_key", return_value='{"code": "x"}')
def test_call_tool_canonical_key_fallback(mock_get, tmp_repo):
    """Test legacy canonical_key field and canonical_keys list fallback."""
    result = _call_tool(tmp_repo, "http://localhost:8000", "get_snippet_by_canonical_key", {"canonical_key": "k1"})
    assert "x" in result

    result = _call_tool(tmp_repo, "http://localhost:8000", "get_snippet_by_key", {"canonical_keys": ["k2"]})
    assert "x" in result


# ---------------------------------------------------------------------------
# _TOOLS structure
# ---------------------------------------------------------------------------


def test_tools_list_structure():
    assert len(_TOOLS) >= 7
    for tool in _TOOLS:
        assert "name" in tool
        assert "description" in tool
        assert "inputSchema" in tool


def test_fs_tool_names():
    assert _FS_TOOL_NAMES == {"read_file", "glob_files", "grep_files"}


# ---------------------------------------------------------------------------
# HarnessMCPServer lifecycle
# ---------------------------------------------------------------------------


def test_mcp_server_start_stop(tmp_repo):
    server = HarnessMCPServer(
        repo_root=tmp_repo,
        base_url="http://localhost:8000",
        port=0,  # auto-assign
    )
    server.start()
    assert server.port > 0
    server.stop()


def test_mcp_server_with_fs_tools(tmp_repo):
    server = HarnessMCPServer(
        repo_root=tmp_repo,
        base_url="http://localhost:8000",
        port=0,
        include_fs_tools=True,
    )
    server.start()
    assert server.port > 0
    server.stop()


# ---------------------------------------------------------------------------
# MCP HTTP endpoint integration
# ---------------------------------------------------------------------------


def test_mcp_server_tools_list(tmp_repo):
    import urllib.request

    server = HarnessMCPServer(
        repo_root=tmp_repo,
        base_url="http://localhost:8000",
        port=0,
        include_fs_tools=True,
    )
    server.start()
    try:
        req = urllib.request.Request(
            f"http://127.0.0.1:{server.port}",
            data=json.dumps({"method": "tools/list", "id": 1}).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read())
        assert "result" in data
        assert "tools" in data["result"]
        tool_names = [t["name"] for t in data["result"]["tools"]]
        assert "read_file" in tool_names
    finally:
        server.stop()


def test_mcp_server_tools_call(tmp_repo):
    import urllib.request

    server = HarnessMCPServer(
        repo_root=tmp_repo,
        base_url="http://localhost:8000",
        port=0,
        include_fs_tools=True,
    )
    server.start()
    try:
        req = urllib.request.Request(
            f"http://127.0.0.1:{server.port}",
            data=json.dumps({
                "method": "tools/call",
                "id": 2,
                "params": {"name": "glob_files", "arguments": {"pattern": "**/*.py"}},
            }).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read())
        assert "result" in data
        content = data["result"]["content"]
        assert any("main.py" in c["text"] for c in content)
    finally:
        server.stop()


def test_mcp_server_initialize(tmp_repo):
    import urllib.request

    server = HarnessMCPServer(repo_root=tmp_repo, base_url="http://localhost:8000", port=0)
    server.start()
    try:
        req = urllib.request.Request(
            f"http://127.0.0.1:{server.port}",
            data=json.dumps({"method": "initialize", "id": 0}).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read())
        assert data["result"]["serverInfo"]["name"] == "vsevals-harness"
    finally:
        server.stop()


def test_mcp_server_fs_tools_disabled(tmp_repo):
    import urllib.request

    server = HarnessMCPServer(
        repo_root=tmp_repo,
        base_url="http://localhost:8000",
        port=0,
        include_fs_tools=False,
    )
    server.start()
    try:
        req = urllib.request.Request(
            f"http://127.0.0.1:{server.port}",
            data=json.dumps({
                "method": "tools/call",
                "id": 3,
                "params": {"name": "read_file", "arguments": {"path": "src/main.py"}},
            }).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read())
        # Should return error since fs tools are disabled
        assert "error" in data
    finally:
        server.stop()
