"""Tests for vsevals.providers.claudecode — stream parsers, invocation, execution, orchestrator."""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from vsevals.models import RunConfig, ToolTrace
from vsevals.providers.claudecode import (
    ClaudeCodeInvocation,
    ClaudeCodeRawOutput,
    ClaudeCodeParsed,
    _build_claudecode_invocation,
    _execute_claudecode,
    _extract_snippet_count,
    _extract_stream_error,
    _parse_claudecode_output,
    _parse_claudecode_stream_json,
    call_claudecode,
)


# ---------------------------------------------------------------------------
# _extract_snippet_count
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "input_str, expected",
    [
        # Direct list
        ('[1, 2, 3]', 3),
        ('[]', 0),
        ('["a"]', 1),
        # Wrapped in {"result": [...]}
        ('{"result": [1, 2]}', 2),
        ('{"result": []}', 0),
        ('{"result": ["x", "y", "z", "w"]}', 4),
        # Not a list at top or under "result"
        ('{"result": "string"}', None),
        ('{"other_key": [1]}', None),
        ('42', None),
        ('"just a string"', None),
        # Malformed JSON
        ('not json at all', None),
        ('{broken', None),
        ('', None),
    ],
    ids=[
        "direct_list_3",
        "direct_empty_list",
        "direct_list_1",
        "wrapped_list_2",
        "wrapped_empty_list",
        "wrapped_list_4",
        "result_not_list",
        "no_result_key",
        "plain_int",
        "plain_string",
        "invalid_json",
        "broken_json",
        "empty_string",
    ],
)
def test_extract_snippet_count(input_str, expected):
    assert _extract_snippet_count(input_str) == expected


def test_extract_snippet_count_nested_dict_with_list_result():
    """A dict with 'result' key pointing to a list should return length."""
    data = {"result": [{"id": "s1"}, {"id": "s2"}], "extra": "ignored"}
    assert _extract_snippet_count(json.dumps(data)) == 2


# ---------------------------------------------------------------------------
# _extract_stream_error
# ---------------------------------------------------------------------------


def test_extract_stream_error_no_error():
    stdout = "\n".join([
        json.dumps({"type": "system", "subtype": "init"}),
        json.dumps({"type": "assistant", "message": {"content": [{"type": "text", "text": "hello"}]}}),
        json.dumps({"type": "result", "subtype": "success", "result": "done"}),
    ])
    assert _extract_stream_error(stdout) is None


def test_extract_stream_error_result_is_error_with_result_field():
    stdout = "\n".join([
        json.dumps({"type": "result", "is_error": True, "result": "rate limited"}),
    ])
    assert _extract_stream_error(stdout) == "rate limited"


def test_extract_stream_error_result_is_error_with_error_field():
    stdout = "\n".join([
        json.dumps({"type": "result", "is_error": True, "error": "auth failure"}),
    ])
    assert _extract_stream_error(stdout) == "auth failure"


def test_extract_stream_error_result_is_error_falls_back_to_assistant_error():
    """When result event has is_error but no result/error, use assistant error."""
    stdout = "\n".join([
        json.dumps({"type": "assistant", "error": "upstream timeout"}),
        json.dumps({"type": "result", "is_error": True}),
    ])
    assert _extract_stream_error(stdout) == "upstream timeout"


def test_extract_stream_error_result_is_error_no_message_at_all():
    stdout = json.dumps({"type": "result", "is_error": True})
    assert _extract_stream_error(stdout) == "claudecode stream returned is_error=true"


def test_extract_stream_error_assistant_error_only():
    """An assistant error without a result is_error event is still returned."""
    stdout = "\n".join([
        json.dumps({"type": "assistant", "error": "something broke"}),
        json.dumps({"type": "result", "subtype": "success", "result": "ok"}),
    ])
    assert _extract_stream_error(stdout) == "something broke"


def test_extract_stream_error_first_assistant_error_wins():
    """Only the first assistant error is captured."""
    stdout = "\n".join([
        json.dumps({"type": "assistant", "error": "first error"}),
        json.dumps({"type": "assistant", "error": "second error"}),
    ])
    assert _extract_stream_error(stdout) == "first error"


def test_extract_stream_error_ignores_non_dict_lines():
    stdout = "\n".join([
        '"just a string"',
        "42",
        json.dumps({"type": "result", "is_error": True, "result": "bad"}),
    ])
    assert _extract_stream_error(stdout) == "bad"


def test_extract_stream_error_skips_blank_and_malformed_lines():
    stdout = "\n\n  \nnot json\n" + json.dumps({"type": "assistant", "error": "found it"})
    assert _extract_stream_error(stdout) == "found it"


def test_extract_stream_error_empty_string():
    assert _extract_stream_error("") is None


def test_extract_stream_error_is_error_false_ignored():
    """is_error=false should not trigger an error."""
    stdout = json.dumps({"type": "result", "is_error": False, "result": "fine"})
    assert _extract_stream_error(stdout) is None


# ---------------------------------------------------------------------------
# _parse_claudecode_stream_json — new format
# ---------------------------------------------------------------------------


def test_parse_stream_system_init_session_id():
    stdout = json.dumps({"type": "system", "subtype": "init", "session_id": "sess-123"})
    output, pt, ct, cached, thinking, sid, traces = _parse_claudecode_stream_json(stdout)
    assert sid == "sess-123"
    assert output == ""
    assert traces == []


def test_parse_stream_system_init_session_id_camelcase():
    stdout = json.dumps({"type": "system", "subtype": "init", "sessionId": "sess-456"})
    _, _, _, _, _, sid, _ = _parse_claudecode_stream_json(stdout)
    assert sid == "sess-456"


def test_parse_stream_assistant_text_block():
    stdout = json.dumps({
        "type": "assistant",
        "message": {
            "id": "msg-1",
            "usage": {"input_tokens": 100, "output_tokens": 50},
            "content": [{"type": "text", "text": "Hello world"}],
        },
    })
    output, pt, ct, cached, thinking, sid, traces = _parse_claudecode_stream_json(stdout)
    assert output == "Hello world"
    assert pt == 100
    assert ct == 50
    assert cached == 0
    assert thinking is None


def test_parse_stream_assistant_deduplicates_by_msg_id():
    """Duplicate message IDs should not double-count tokens."""
    evt = {
        "type": "assistant",
        "message": {
            "id": "msg-dup",
            "usage": {"input_tokens": 100, "output_tokens": 50},
            "content": [{"type": "text", "text": "text"}],
        },
    }
    stdout = "\n".join([json.dumps(evt), json.dumps(evt)])
    _, pt, ct, _, _, _, _ = _parse_claudecode_stream_json(stdout)
    assert pt == 100
    assert ct == 50


def test_parse_stream_assistant_cached_tokens():
    stdout = json.dumps({
        "type": "assistant",
        "message": {
            "id": "msg-c",
            "usage": {"input_tokens": 200, "output_tokens": 30, "cache_read_input_tokens": 80},
            "content": [],
        },
    })
    _, pt, ct, cached, _, _, _ = _parse_claudecode_stream_json(stdout)
    assert cached == 80


def test_parse_stream_assistant_thinking_tokens():
    stdout = json.dumps({
        "type": "assistant",
        "message": {
            "id": "msg-t",
            "usage": {"input_tokens": 10, "output_tokens": 5, "thinking_tokens": 200},
            "content": [],
        },
    })
    _, _, _, _, thinking, _, _ = _parse_claudecode_stream_json(stdout)
    assert thinking == 200


def test_parse_stream_assistant_reasoning_tokens_alias():
    stdout = json.dumps({
        "type": "assistant",
        "message": {
            "id": "msg-r",
            "usage": {"input_tokens": 10, "output_tokens": 5, "reasoning_tokens": 150},
            "content": [],
        },
    })
    _, _, _, _, thinking, _, _ = _parse_claudecode_stream_json(stdout)
    assert thinking == 150


def test_parse_stream_tool_use_and_tool_result():
    """New format: tool_use in assistant, tool_result in user."""
    lines = [
        json.dumps({
            "type": "assistant",
            "message": {
                "id": "msg-tool",
                "usage": {"input_tokens": 10, "output_tokens": 5},
                "content": [
                    {"type": "tool_use", "id": "call-1", "name": "mcp__voltsnip__search_memory", "input": {"q": "test"}},
                ],
            },
        }),
        json.dumps({
            "type": "user",
            "message": {
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": "call-1",
                        "content": [{"type": "text", "text": '[{"id":"s1"}]'}],
                    },
                ],
            },
        }),
    ]
    stdout = "\n".join(lines)
    _, _, _, _, _, _, traces = _parse_claudecode_stream_json(stdout)
    assert len(traces) == 1
    assert traces[0].tool_name == "mcp__voltsnip__search_memory"
    assert traces[0].tool_call_id == "call-1"
    assert traces[0].tool_result == {"retrieved": 1}
    assert traces[0].error is None
    assert traces[0].roundtrip == 1


def test_parse_stream_tool_result_with_error():
    lines = [
        json.dumps({
            "type": "assistant",
            "message": {
                "id": "msg-te",
                "usage": {"input_tokens": 5, "output_tokens": 2},
                "content": [
                    {"type": "tool_use", "id": "call-err", "name": "search", "input": {}},
                ],
            },
        }),
        json.dumps({
            "type": "user",
            "message": {
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": "call-err",
                        "error": "timeout",
                        "content": "",
                    },
                ],
            },
        }),
    ]
    stdout = "\n".join(lines)
    _, _, _, _, _, _, traces = _parse_claudecode_stream_json(stdout)
    assert len(traces) == 1
    assert traces[0].error == "timeout"
    # snippet_count should be None when there's an error
    assert traces[0].tool_result == {"raw": ""}


def test_parse_stream_tool_result_string_content():
    """tool_result content can be a plain string."""
    lines = [
        json.dumps({
            "type": "assistant",
            "message": {
                "id": "msg-sc",
                "usage": {"input_tokens": 5, "output_tokens": 2},
                "content": [
                    {"type": "tool_use", "id": "call-sc", "name": "fetch", "input": {}},
                ],
            },
        }),
        json.dumps({
            "type": "user",
            "message": {
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": "call-sc",
                        "content": "plain string result",
                    },
                ],
            },
        }),
    ]
    stdout = "\n".join(lines)
    _, _, _, _, _, _, traces = _parse_claudecode_stream_json(stdout)
    assert len(traces) == 1
    assert traces[0].tool_result == {"raw": "plain string result"}


def test_parse_stream_unclosed_tool_call():
    """A tool_use with no matching tool_result should produce an error trace."""
    stdout = json.dumps({
        "type": "assistant",
        "message": {
            "id": "msg-orphan",
            "usage": {"input_tokens": 5, "output_tokens": 2},
            "content": [
                {"type": "tool_use", "id": "call-orphan", "name": "search", "input": {"q": "lost"}},
            ],
        },
    })
    _, _, _, _, _, _, traces = _parse_claudecode_stream_json(stdout)
    assert len(traces) == 1
    assert traces[0].error == "no tool result received"
    assert traces[0].tool_result is None


def test_parse_stream_last_text_block_wins():
    """The final non-empty text block becomes final_output."""
    lines = [
        json.dumps({
            "type": "assistant",
            "message": {
                "id": "msg-a",
                "usage": {"input_tokens": 5, "output_tokens": 5},
                "content": [{"type": "text", "text": "first answer"}],
            },
        }),
        json.dumps({
            "type": "assistant",
            "message": {
                "id": "msg-b",
                "usage": {"input_tokens": 5, "output_tokens": 5},
                "content": [{"type": "text", "text": "second answer"}],
            },
        }),
    ]
    stdout = "\n".join(lines)
    output, _, _, _, _, _, _ = _parse_claudecode_stream_json(stdout)
    assert output == "second answer"


def test_parse_stream_whitespace_only_text_block_ignored():
    stdout = json.dumps({
        "type": "assistant",
        "message": {
            "id": "msg-ws",
            "usage": {"input_tokens": 5, "output_tokens": 5},
            "content": [{"type": "text", "text": "   \n  "}],
        },
    })
    output, _, _, _, _, _, _ = _parse_claudecode_stream_json(stdout)
    assert output == ""


# ---------------------------------------------------------------------------
# _parse_claudecode_stream_json — legacy format
# ---------------------------------------------------------------------------


def test_parse_stream_legacy_messagestart():
    stdout = json.dumps({
        "type": "messageStart",
        "message": {
            "usage": {"input_tokens": 300, "cache_read_input_tokens": 50},
        },
    })
    _, pt, _, cached, _, _, _ = _parse_claudecode_stream_json(stdout)
    assert pt == 300
    assert cached == 50


def test_parse_stream_legacy_messageend():
    stdout = json.dumps({
        "type": "messageEnd",
        "message": {
            "usage": {"output_tokens": 120},
            "content": [{"type": "text", "text": "legacy output"}],
        },
    })
    output, _, ct, _, _, _, _ = _parse_claudecode_stream_json(stdout)
    assert ct == 120
    assert output == "legacy output"


def test_parse_stream_legacy_text_event():
    lines = [
        json.dumps({"type": "text", "text": "part1 "}),
        json.dumps({"type": "text", "text": "part2"}),
    ]
    stdout = "\n".join(lines)
    output, _, _, _, _, _, _ = _parse_claudecode_stream_json(stdout)
    assert output == "part1 part2"


def test_parse_stream_legacy_tooluse_and_toolresult():
    lines = [
        json.dumps({"type": "toolUse", "id": "tc-1", "name": "voltsnip_search", "input": {"key": "val"}}),
        json.dumps({
            "type": "toolResult",
            "toolUseId": "tc-1",
            "content": [{"type": "text", "text": '["a","b"]'}],
        }),
    ]
    stdout = "\n".join(lines)
    _, _, _, _, _, _, traces = _parse_claudecode_stream_json(stdout)
    assert len(traces) == 1
    assert traces[0].tool_name == "voltsnip_search"
    assert traces[0].tool_result == {"retrieved": 2}


def test_parse_stream_legacy_toolresult_with_error():
    lines = [
        json.dumps({"type": "toolUse", "id": "tc-e", "name": "search", "input": {}}),
        json.dumps({
            "type": "toolResult",
            "toolUseId": "tc-e",
            "error": "not found",
            "content": [],
        }),
    ]
    stdout = "\n".join(lines)
    _, _, _, _, _, _, traces = _parse_claudecode_stream_json(stdout)
    assert len(traces) == 1
    assert traces[0].error == "not found"


def test_parse_stream_legacy_result_success():
    stdout = json.dumps({"type": "result", "subtype": "success", "result": "final answer"})
    output, _, _, _, _, _, _ = _parse_claudecode_stream_json(stdout)
    assert output == "final answer"


def test_parse_stream_legacy_result_success_not_overridden_if_output_exists():
    """If final_output is already set, result success does not override it."""
    lines = [
        json.dumps({"type": "text", "text": "existing text"}),
        json.dumps({"type": "result", "subtype": "success", "result": "should not replace"}),
    ]
    stdout = "\n".join(lines)
    output, _, _, _, _, _, _ = _parse_claudecode_stream_json(stdout)
    assert output == "existing text"


def test_parse_stream_session_id_from_generic_field():
    """Session ID can come from any event's session_id or sessionId field."""
    stdout = json.dumps({"type": "text", "text": "hi", "sessionId": "fallback-sid"})
    _, _, _, _, _, sid, _ = _parse_claudecode_stream_json(stdout)
    assert sid == "fallback-sid"


def test_parse_stream_empty_input():
    output, pt, ct, cached, thinking, sid, traces = _parse_claudecode_stream_json("")
    assert output == ""
    assert pt == 0
    assert ct == 0
    assert cached == 0
    assert thinking is None
    assert sid is None
    assert traces == []


def test_parse_stream_malformed_lines_skipped():
    stdout = "not json\n{bad json\n" + json.dumps({"type": "text", "text": "ok"})
    output, _, _, _, _, _, _ = _parse_claudecode_stream_json(stdout)
    assert output == "ok"


def test_parse_stream_legacy_messagestart_thinking_tokens():
    stdout = json.dumps({
        "type": "messageStart",
        "message": {
            "usage": {"input_tokens": 10, "thinking_tokens": 500},
        },
    })
    _, _, _, _, thinking, _, _ = _parse_claudecode_stream_json(stdout)
    assert thinking == 500


# ---------------------------------------------------------------------------
# ClaudeCodeInvocation — cleanup
# ---------------------------------------------------------------------------


def test_cleanup_removes_mcp_config(tmp_path):
    mcp_file = tmp_path / "mcp_config.json"
    mcp_file.write_text("{}")
    inv = ClaudeCodeInvocation(
        cmd=["echo"],
        env={},
        cwd=None,
        timeout=10.0,
        _mcp_config_path=str(mcp_file),
    )
    inv.cleanup()
    assert not mcp_file.exists()


def test_cleanup_removes_debug_file(tmp_path):
    debug_file = tmp_path / "debug.log"
    debug_file.write_text("debug output")
    inv = ClaudeCodeInvocation(
        cmd=["echo"],
        env={},
        cwd=None,
        timeout=10.0,
        _debug_file_path=str(debug_file),
    )
    inv.cleanup()
    assert not debug_file.exists()


def test_cleanup_removes_sidecar_dir(tmp_path):
    sidecar = tmp_path / "sidecar"
    sidecar.mkdir()
    (sidecar / "CLAUDE.md").write_text("content")
    inv = ClaudeCodeInvocation(
        cmd=["echo"],
        env={},
        cwd=None,
        timeout=10.0,
        _sidecar_dir=str(sidecar),
    )
    inv.cleanup()
    assert not sidecar.exists()


def test_cleanup_tolerates_missing_files():
    """cleanup() should not raise even if paths don't exist."""
    inv = ClaudeCodeInvocation(
        cmd=["echo"],
        env={},
        cwd=None,
        timeout=10.0,
        _mcp_config_path="/nonexistent/path.json",
        _debug_file_path="/nonexistent/debug.log",
        _sidecar_dir="/nonexistent/sidecar_dir",
    )
    inv.cleanup()  # should not raise


def test_cleanup_removes_all_three(tmp_path):
    mcp_file = tmp_path / "mcp.json"
    mcp_file.write_text("{}")
    debug_file = tmp_path / "debug.log"
    debug_file.write_text("log")
    sidecar = tmp_path / "sidecar"
    sidecar.mkdir()
    (sidecar / "file.txt").write_text("x")

    inv = ClaudeCodeInvocation(
        cmd=["echo"],
        env={},
        cwd=None,
        timeout=10.0,
        _mcp_config_path=str(mcp_file),
        _debug_file_path=str(debug_file),
        _sidecar_dir=str(sidecar),
    )
    inv.cleanup()
    assert not mcp_file.exists()
    assert not debug_file.exists()
    assert not sidecar.exists()


def test_cleanup_noop_when_paths_empty():
    """Empty string paths should cause no action."""
    inv = ClaudeCodeInvocation(
        cmd=["echo"],
        env={},
        cwd=None,
        timeout=10.0,
        _mcp_config_path="",
        _debug_file_path="",
        _sidecar_dir="",
    )
    inv.cleanup()  # should not raise


# ---------------------------------------------------------------------------
# _build_claudecode_invocation
# ---------------------------------------------------------------------------


def _make_cfg(**overrides) -> RunConfig:
    defaults = dict(
        voltsnip_base_url="http://localhost:8000",
        llm_timeout_seconds=60,
        structured_output=True,
    )
    defaults.update(overrides)
    return RunConfig(**defaults)


def test_build_invocation_no_tools():
    cfg = _make_cfg()
    inv = _build_claudecode_invocation(
        model_id="claude-haiku-4-5",
        combined_prompt="fix the bug",
        cfg=cfg,
        tool_schemas=None,
        sidecar_files=None,
        timeout=60.0,
    )
    try:
        assert "claude" in inv.cmd[0]
        assert "-p" in inv.cmd
        assert "fix the bug" in inv.cmd
        assert "--model" in inv.cmd
        assert "claude-haiku-4-5" in inv.cmd
        # No MCP config when tools are disabled
        assert inv._mcp_config_path == ""
        # Should still have a sidecar dir as cwd
        assert inv._sidecar_dir
        assert inv.cwd == inv._sidecar_dir
        # Env should have NO_COLOR
        assert inv.env.get("NO_COLOR") == "1"
    finally:
        inv.cleanup()


def test_build_invocation_with_tool_schemas():
    cfg = _make_cfg()
    inv = _build_claudecode_invocation(
        model_id="claude-haiku-4-5",
        combined_prompt="prompt",
        cfg=cfg,
        tool_schemas=[{"name": "test_tool"}],
        sidecar_files=None,
        timeout=60.0,
    )
    try:
        assert inv._mcp_config_path != ""
        assert Path(inv._mcp_config_path).exists()
        mcp_data = json.loads(Path(inv._mcp_config_path).read_text())
        assert "mcpServers" in mcp_data
        assert "voltsnip" in mcp_data["mcpServers"]
        assert mcp_data["mcpServers"]["voltsnip"]["url"] == "http://localhost:8000/mcp"
        assert "--mcp-config" in inv.cmd
    finally:
        inv.cleanup()


def test_build_invocation_custom_voltsnip_base_url():
    cfg = _make_cfg(voltsnip_base_url="https://api.example.com/")
    inv = _build_claudecode_invocation(
        model_id="claude-haiku-4-5",
        combined_prompt="prompt",
        cfg=cfg,
        tool_schemas=[{"name": "tool"}],
        sidecar_files=None,
        timeout=60.0,
    )
    try:
        mcp_data = json.loads(Path(inv._mcp_config_path).read_text())
        # Trailing slash should be stripped then /mcp appended
        assert mcp_data["mcpServers"]["voltsnip"]["url"] == "https://api.example.com/mcp"
    finally:
        inv.cleanup()


def test_build_invocation_sidecar_files_written(tmp_path):
    cfg = _make_cfg()
    inv = _build_claudecode_invocation(
        model_id="claude-haiku-4-5",
        combined_prompt="prompt",
        cfg=cfg,
        tool_schemas=None,
        sidecar_files={"CLAUDE.md": "# Memory content", "data.txt": "hello"},
        timeout=60.0,
    )
    try:
        cwd = Path(inv.cwd)
        assert (cwd / "CLAUDE.md").read_text() == "# Memory content"
        assert (cwd / "data.txt").read_text() == "hello"
    finally:
        inv.cleanup()


def test_build_invocation_removes_claudecode_env_var():
    cfg = _make_cfg()
    with patch.dict(os.environ, {"CLAUDECODE": "1"}):
        inv = _build_claudecode_invocation(
            model_id="claude-haiku-4-5",
            combined_prompt="prompt",
            cfg=cfg,
            tool_schemas=None,
            sidecar_files=None,
            timeout=60.0,
        )
        try:
            assert "CLAUDECODE" not in inv.env
        finally:
            inv.cleanup()


def test_build_invocation_sets_claude_model_env():
    cfg = _make_cfg()
    with patch.dict(os.environ, {}, clear=False):
        # Remove CLAUDE_MODEL if present
        os.environ.pop("CLAUDE_MODEL", None)
        inv = _build_claudecode_invocation(
            model_id="claude-opus-4-5",
            combined_prompt="prompt",
            cfg=cfg,
            tool_schemas=None,
            sidecar_files=None,
            timeout=60.0,
        )
        try:
            assert inv.env["CLAUDE_MODEL"] == "claude-opus-4-5"
        finally:
            inv.cleanup()


def test_build_invocation_allowed_tools_with_schemas():
    """When tool_schemas are provided, allowedTools should contain voltsnip tools."""
    cfg = _make_cfg()
    inv = _build_claudecode_invocation(
        model_id="claude-haiku-4-5",
        combined_prompt="prompt",
        cfg=cfg,
        tool_schemas=[{"name": "tool"}],
        sidecar_files=None,
        timeout=60.0,
    )
    try:
        idx = inv.cmd.index("--allowedTools")
        allowed = inv.cmd[idx + 1]
        assert "mcp__voltsnip__search_memory" in allowed
    finally:
        inv.cleanup()


def test_build_invocation_no_tools_empty_allowed():
    """Without tool_schemas, allowedTools should be empty string."""
    cfg = _make_cfg()
    inv = _build_claudecode_invocation(
        model_id="claude-haiku-4-5",
        combined_prompt="prompt",
        cfg=cfg,
        tool_schemas=None,
        sidecar_files=None,
        timeout=60.0,
    )
    try:
        idx = inv.cmd.index("--allowedTools")
        assert inv.cmd[idx + 1] == ""
    finally:
        inv.cleanup()


def test_build_invocation_disallowed_tools_always_set():
    """Disallowed tools (Bash, Edit, etc.) should always be in --disallowedTools."""
    cfg = _make_cfg()
    inv = _build_claudecode_invocation(
        model_id="claude-haiku-4-5",
        combined_prompt="prompt",
        cfg=cfg,
        tool_schemas=None,
        sidecar_files=None,
        timeout=60.0,
    )
    try:
        idx = inv.cmd.index("--disallowedTools")
        disallowed = inv.cmd[idx + 1]
        assert "Bash" in disallowed
        assert "Edit" in disallowed
        assert "Write" in disallowed
    finally:
        inv.cleanup()


# ---------------------------------------------------------------------------
# _execute_claudecode
# ---------------------------------------------------------------------------


@patch("vsevals.providers.claudecode.subprocess.run")
def test_execute_claudecode_success(mock_run, tmp_path):
    mock_run.return_value = MagicMock(
        returncode=0,
        stdout='{"type":"text","text":"hello"}\n',
        stderr="",
    )
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    inv = ClaudeCodeInvocation(
        cmd=["claude", "-p", "test"],
        env={"NO_COLOR": "1"},
        cwd="/tmp",
        timeout=60.0,
    )
    raw = _execute_claudecode(inv, run_dir)
    assert raw.returncode == 0
    assert raw.stdout_path.exists()
    assert raw.stderr_path.exists()
    assert raw.stdout_path.read_text() == '{"type":"text","text":"hello"}\n'
    assert isinstance(raw.started_at, datetime)
    assert isinstance(raw.finished_at, datetime)


@patch("vsevals.providers.claudecode.subprocess.run")
def test_execute_claudecode_nonzero_with_stdout(mock_run, tmp_path):
    """Non-zero exit with stdout should NOT raise (soft failure path)."""
    mock_run.return_value = MagicMock(
        returncode=1,
        stdout='{"type":"result","is_error":true,"result":"rate limited"}',
        stderr="warn: limit reached",
    )
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    inv = ClaudeCodeInvocation(
        cmd=["claude", "-p", "test"],
        env={},
        cwd=None,
        timeout=60.0,
    )
    raw = _execute_claudecode(inv, run_dir)
    assert raw.returncode == 1


@patch("vsevals.providers.claudecode.subprocess.run")
def test_execute_claudecode_nonzero_no_stdout_raises(mock_run, tmp_path):
    """Non-zero exit with empty stdout should raise RuntimeError."""
    mock_run.return_value = MagicMock(
        returncode=1,
        stdout="",
        stderr="fatal: auth error",
    )
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    inv = ClaudeCodeInvocation(
        cmd=["claude", "-p", "test"],
        env={},
        cwd=None,
        timeout=60.0,
    )
    with pytest.raises(RuntimeError, match="claude failed"):
        _execute_claudecode(inv, run_dir)


@patch("vsevals.providers.claudecode.subprocess.run")
def test_execute_claudecode_persists_files(mock_run, tmp_path):
    """Stdout and stderr must be persisted to disk before any error checking."""
    mock_run.return_value = MagicMock(
        returncode=0,
        stdout="stdout content",
        stderr="stderr content",
    )
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    inv = ClaudeCodeInvocation(cmd=["test"], env={}, cwd=None, timeout=10.0)
    raw = _execute_claudecode(inv, run_dir)
    assert (run_dir / "subprocess.stdout.claudecode.jsonl").read_text() == "stdout content"
    assert (run_dir / "subprocess.stderr.claudecode.txt").read_text() == "stderr content"


# ---------------------------------------------------------------------------
# _parse_claudecode_output
# ---------------------------------------------------------------------------


def test_parse_claudecode_output(tmp_path):
    stdout_path = tmp_path / "subprocess.stdout.claudecode.jsonl"
    stderr_path = tmp_path / "subprocess.stderr.claudecode.txt"
    stdout_content = "\n".join([
        json.dumps({"type": "system", "subtype": "init", "session_id": "s1"}),
        json.dumps({
            "type": "assistant",
            "message": {
                "id": "m1",
                "usage": {"input_tokens": 50, "output_tokens": 25, "cache_read_input_tokens": 10},
                "content": [{"type": "text", "text": "parsed output"}],
            },
        }),
    ])
    stdout_path.write_text(stdout_content)
    stderr_path.write_text("")
    raw = ClaudeCodeRawOutput(
        returncode=0,
        stdout_path=stdout_path,
        stderr_path=stderr_path,
        started_at=datetime.now(timezone.utc),
        finished_at=datetime.now(timezone.utc),
    )
    parsed = _parse_claudecode_output(raw)
    assert parsed.raw_text == "parsed output"
    assert parsed.prompt_tokens == 50
    assert parsed.completion_tokens == 25
    assert parsed.cached_tokens == 10
    assert parsed.session_id == "s1"


# ---------------------------------------------------------------------------
# call_claudecode — orchestrator
# ---------------------------------------------------------------------------


@patch("vsevals.providers.claudecode._execute_claudecode")
@patch("vsevals.providers.claudecode._build_claudecode_invocation")
def test_call_claudecode_success(mock_build, mock_execute, tmp_path):
    """Orchestrator wires build -> execute -> parse correctly."""
    # Set up mock invocation
    mock_inv = MagicMock(spec=ClaudeCodeInvocation)
    mock_inv._debug_file_path = ""
    mock_inv._mcp_config_path = ""
    mock_inv._sidecar_dir = ""
    mock_build.return_value = mock_inv

    # Set up mock execution output
    stdout_path = tmp_path / "subprocess.stdout.claudecode.jsonl"
    stderr_path = tmp_path / "subprocess.stderr.claudecode.txt"
    stream = "\n".join([
        json.dumps({"type": "system", "subtype": "init", "session_id": "test-session"}),
        json.dumps({
            "type": "assistant",
            "message": {
                "id": "m1",
                "usage": {"input_tokens": 100, "output_tokens": 50},
                "content": [{"type": "text", "text": '{"code": "def fix(): pass", "comments": "fixed"}'}],
            },
        }),
        json.dumps({"type": "result", "subtype": "success", "result": "ok"}),
    ])
    stdout_path.write_text(stream)
    stderr_path.write_text("")

    mock_execute.return_value = ClaudeCodeRawOutput(
        returncode=0,
        stdout_path=stdout_path,
        stderr_path=stderr_path,
        started_at=datetime.now(timezone.utc),
        finished_at=datetime.now(timezone.utc),
    )

    cfg = _make_cfg()
    result = call_claudecode(
        model_id="claude-haiku-4-5",
        system_prompt="You are a test assistant.",
        user_prompt="Fix the bug.",
        cfg=cfg,
        run_dir=str(tmp_path),
    )
    assert result.request_id == "test-session"
    assert result.token_usage.prompt_tokens == 100
    assert result.token_usage.completion_tokens == 50
    assert result.parsed_output.code == "def fix(): pass"
    mock_inv.cleanup.assert_called_once()


@patch("vsevals.providers.claudecode._execute_claudecode")
@patch("vsevals.providers.claudecode._build_claudecode_invocation")
def test_call_claudecode_stream_error_raises(mock_build, mock_execute, tmp_path):
    """Orchestrator should raise when stream contains an error."""
    mock_inv = MagicMock(spec=ClaudeCodeInvocation)
    mock_inv._debug_file_path = ""
    mock_inv._mcp_config_path = ""
    mock_inv._sidecar_dir = ""
    mock_build.return_value = mock_inv

    stdout_path = tmp_path / "subprocess.stdout.claudecode.jsonl"
    stderr_path = tmp_path / "subprocess.stderr.claudecode.txt"
    stdout_path.write_text(json.dumps({"type": "result", "is_error": True, "result": "overloaded"}))
    stderr_path.write_text("")

    mock_execute.return_value = ClaudeCodeRawOutput(
        returncode=0,
        stdout_path=stdout_path,
        stderr_path=stderr_path,
        started_at=datetime.now(timezone.utc),
        finished_at=datetime.now(timezone.utc),
    )

    cfg = _make_cfg()
    with pytest.raises(RuntimeError, match="claudecode stream error"):
        call_claudecode(
            model_id="claude-haiku-4-5",
            system_prompt="sys",
            user_prompt="user",
            cfg=cfg,
            run_dir=str(tmp_path),
        )
    # cleanup should still be called even on error
    mock_inv.cleanup.assert_called_once()


@patch("vsevals.providers.claudecode._execute_claudecode")
@patch("vsevals.providers.claudecode._build_claudecode_invocation")
def test_call_claudecode_timeout_calculation_with_tools(mock_build, mock_execute, tmp_path):
    """With tool_schemas, timeout should be max(600, llm_timeout_seconds * 2)."""
    mock_inv = MagicMock(spec=ClaudeCodeInvocation)
    mock_inv._debug_file_path = ""
    mock_inv._mcp_config_path = ""
    mock_inv._sidecar_dir = ""
    mock_build.return_value = mock_inv

    stdout_path = tmp_path / "subprocess.stdout.claudecode.jsonl"
    stderr_path = tmp_path / "subprocess.stderr.claudecode.txt"
    stdout_path.write_text(json.dumps({
        "type": "assistant",
        "message": {
            "id": "m1",
            "usage": {"input_tokens": 5, "output_tokens": 5},
            "content": [{"type": "text", "text": '{"code":"x","comments":""}'}],
        },
    }))
    stderr_path.write_text("")

    mock_execute.return_value = ClaudeCodeRawOutput(
        returncode=0,
        stdout_path=stdout_path,
        stderr_path=stderr_path,
        started_at=datetime.now(timezone.utc),
        finished_at=datetime.now(timezone.utc),
    )

    cfg = _make_cfg(llm_timeout_seconds=60)
    call_claudecode(
        model_id="claude-haiku-4-5",
        system_prompt="sys",
        user_prompt="user",
        cfg=cfg,
        tool_schemas=[{"name": "tool"}],
        run_dir=str(tmp_path),
    )
    # timeout should be max(600, 60*2) = 600
    build_kwargs = mock_build.call_args.kwargs
    assert build_kwargs["timeout"] == 600.0


@patch("vsevals.providers.claudecode._execute_claudecode")
@patch("vsevals.providers.claudecode._build_claudecode_invocation")
def test_call_claudecode_timeout_calculation_no_tools(mock_build, mock_execute, tmp_path):
    """Without tool_schemas, timeout should be llm_timeout_seconds."""
    mock_inv = MagicMock(spec=ClaudeCodeInvocation)
    mock_inv._debug_file_path = ""
    mock_inv._mcp_config_path = ""
    mock_inv._sidecar_dir = ""
    mock_build.return_value = mock_inv

    stdout_path = tmp_path / "subprocess.stdout.claudecode.jsonl"
    stderr_path = tmp_path / "subprocess.stderr.claudecode.txt"
    stdout_path.write_text(json.dumps({
        "type": "assistant",
        "message": {
            "id": "m1",
            "usage": {"input_tokens": 5, "output_tokens": 5},
            "content": [{"type": "text", "text": '{"code":"x","comments":""}'}],
        },
    }))
    stderr_path.write_text("")

    mock_execute.return_value = ClaudeCodeRawOutput(
        returncode=0,
        stdout_path=stdout_path,
        stderr_path=stderr_path,
        started_at=datetime.now(timezone.utc),
        finished_at=datetime.now(timezone.utc),
    )

    cfg = _make_cfg(llm_timeout_seconds=120)
    call_claudecode(
        model_id="claude-haiku-4-5",
        system_prompt="sys",
        user_prompt="user",
        cfg=cfg,
        tool_schemas=None,
        run_dir=str(tmp_path),
    )
    build_kwargs = mock_build.call_args.kwargs
    assert build_kwargs["timeout"] == 120


@patch("vsevals.providers.claudecode._execute_claudecode")
@patch("vsevals.providers.claudecode._build_claudecode_invocation")
def test_call_claudecode_combined_prompt(mock_build, mock_execute, tmp_path):
    """System and user prompts are combined with double newline."""
    mock_inv = MagicMock(spec=ClaudeCodeInvocation)
    mock_inv._debug_file_path = ""
    mock_inv._mcp_config_path = ""
    mock_inv._sidecar_dir = ""
    mock_build.return_value = mock_inv

    stdout_path = tmp_path / "subprocess.stdout.claudecode.jsonl"
    stderr_path = tmp_path / "subprocess.stderr.claudecode.txt"
    stdout_path.write_text(json.dumps({
        "type": "assistant",
        "message": {
            "id": "m1",
            "usage": {"input_tokens": 5, "output_tokens": 5},
            "content": [{"type": "text", "text": '{"code":"","comments":""}'}],
        },
    }))
    stderr_path.write_text("")

    mock_execute.return_value = ClaudeCodeRawOutput(
        returncode=0,
        stdout_path=stdout_path,
        stderr_path=stderr_path,
        started_at=datetime.now(timezone.utc),
        finished_at=datetime.now(timezone.utc),
    )

    cfg = _make_cfg()
    call_claudecode(
        model_id="claude-haiku-4-5",
        system_prompt="System instructions.",
        user_prompt="User request.",
        cfg=cfg,
        run_dir=str(tmp_path),
    )
    build_kwargs = mock_build.call_args.kwargs
    assert build_kwargs["combined_prompt"] == "System instructions.\n\nUser request."


# ---------------------------------------------------------------------------
# Edge cases and integration-style tests
# ---------------------------------------------------------------------------


def test_parse_stream_multiple_tool_roundtrips():
    """Multiple tool roundtrips should produce sequential roundtrip numbers."""
    lines = []
    for i in range(3):
        lines.append(json.dumps({
            "type": "assistant",
            "message": {
                "id": f"msg-{i}",
                "usage": {"input_tokens": 5, "output_tokens": 2},
                "content": [
                    {"type": "tool_use", "id": f"call-{i}", "name": f"tool_{i}", "input": {}},
                ],
            },
        }))
        lines.append(json.dumps({
            "type": "user",
            "message": {
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": f"call-{i}",
                        "content": "result",
                    },
                ],
            },
        }))

    stdout = "\n".join(lines)
    _, _, _, _, _, _, traces = _parse_claudecode_stream_json(stdout)
    assert len(traces) == 3
    assert [t.roundtrip for t in traces] == [1, 2, 3]
    assert [t.tool_name for t in traces] == ["tool_0", "tool_1", "tool_2"]


def test_parse_stream_snippet_count_in_tool_result():
    """When tool result is a valid list JSON, result should contain retrieved count."""
    lines = [
        json.dumps({
            "type": "assistant",
            "message": {
                "id": "msg-snip",
                "usage": {"input_tokens": 5, "output_tokens": 2},
                "content": [
                    {"type": "tool_use", "id": "call-snip", "name": "search", "input": {}},
                ],
            },
        }),
        json.dumps({
            "type": "user",
            "message": {
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": "call-snip",
                        "content": json.dumps({"result": [{"id": "a"}, {"id": "b"}, {"id": "c"}]}),
                    },
                ],
            },
        }),
    ]
    stdout = "\n".join(lines)
    _, _, _, _, _, _, traces = _parse_claudecode_stream_json(stdout)
    assert traces[0].tool_result == {"retrieved": 3}


def test_parse_stream_tool_result_raw_truncated():
    """Non-list tool results should be stored truncated to 200 chars."""
    long_text = "x" * 500
    lines = [
        json.dumps({
            "type": "assistant",
            "message": {
                "id": "msg-long",
                "usage": {"input_tokens": 5, "output_tokens": 2},
                "content": [
                    {"type": "tool_use", "id": "call-long", "name": "fetch", "input": {}},
                ],
            },
        }),
        json.dumps({
            "type": "user",
            "message": {
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": "call-long",
                        "content": long_text,
                    },
                ],
            },
        }),
    ]
    stdout = "\n".join(lines)
    _, _, _, _, _, _, traces = _parse_claudecode_stream_json(stdout)
    assert len(traces[0].tool_result["raw"]) == 200


def test_parse_stream_messageend_no_output_fills_from_content():
    """Legacy messageEnd populates final_output from content when no prior output."""
    stdout = json.dumps({
        "type": "messageEnd",
        "message": {
            "usage": {"output_tokens": 10},
            "content": [
                {"type": "text", "text": "line1"},
                {"type": "text", "text": "line2"},
            ],
        },
    })
    output, _, _, _, _, _, _ = _parse_claudecode_stream_json(stdout)
    assert output == "line1\nline2"
