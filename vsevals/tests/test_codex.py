"""Comprehensive tests for vsevals.providers.codex module.

Tests cover:
  - _extract_codex_tokens: nested/flat usage formats, cached/thinking tokens
  - _extract_codex_tool_traces: function_call pairs, output_item.added, mcp_tool_call
  - _extract_codex_stream_error: error, response.failed, response.incomplete events
  - CodexInvocation.cleanup: stops harness_server, removes tmp_schema and sidecar_dir
  - _build_codex_invocation: cmd assembly, MCP config, reasoning effort, structured output
  - _execute_codex: subprocess invocation, file persistence, error handling
  - _parse_codex_output: reads disk files, extracts tokens and traces
  - call_codex: full orchestrator
"""

from __future__ import annotations

import json
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from vsevals.models import RunConfig, ToolTrace
from vsevals.providers.codex import (
    CodexInvocation,
    CodexParsed,
    CodexRawOutput,
    _build_codex_invocation,
    _execute_codex,
    _extract_codex_stream_error,
    _extract_codex_tokens,
    _extract_codex_tool_traces,
    _parse_codex_output,
    call_codex,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _jsonl(*dicts: dict) -> str:
    """Build a JSONL string from dictionaries."""
    return "\n".join(json.dumps(d) for d in dicts)


def _make_run_config(**overrides) -> RunConfig:
    defaults = dict(
        api_key="test-key",
        voltsnip_base_url="http://localhost:8000",
        scoring_judge_model="mock:default",
        structured_output=False,
    )
    defaults.update(overrides)
    return RunConfig(**defaults)


# ===========================================================================
# 1. _extract_codex_tokens
# ===========================================================================


def test_extract_tokens_empty():
    """Empty input returns all zeros and None thinking."""
    pt, ct, cached, thinking = _extract_codex_tokens("")
    assert (pt, ct, cached, thinking) == (0, 0, 0, None)


def test_extract_tokens_nested_response_done():
    """Nested usage inside response.done -> response.usage is extracted."""
    jsonl = _jsonl({
        "type": "response.done",
        "response": {
            "usage": {
                "input_tokens": 100,
                "output_tokens": 50,
            }
        }
    })
    pt, ct, cached, thinking = _extract_codex_tokens(jsonl)
    assert pt == 100
    assert ct == 50
    assert cached == 0
    assert thinking is None


def test_extract_tokens_flat_usage():
    """Flat usage dict at top level is extracted."""
    jsonl = _jsonl({
        "usage": {
            "prompt_tokens": 200,
            "completion_tokens": 80,
        }
    })
    pt, ct, cached, thinking = _extract_codex_tokens(jsonl)
    assert pt == 200
    assert ct == 80


def test_extract_tokens_direct_obj_keys():
    """Token counts at the top-level object keys (no usage sub-dict)."""
    jsonl = _jsonl({
        "input_tokens": 30,
        "output_tokens": 10,
    })
    pt, ct, cached, thinking = _extract_codex_tokens(jsonl)
    assert pt == 30
    assert ct == 10


def test_extract_tokens_cached_tokens():
    """Cached tokens are extracted from input_tokens_details or prompt_tokens_details."""
    jsonl = _jsonl({
        "type": "response.done",
        "response": {
            "usage": {
                "input_tokens": 500,
                "output_tokens": 100,
                "input_tokens_details": {"cached_tokens": 200},
            }
        }
    })
    pt, ct, cached, thinking = _extract_codex_tokens(jsonl)
    assert pt == 500
    assert ct == 100
    assert cached == 200


def test_extract_tokens_prompt_tokens_details_cached():
    """prompt_tokens_details.cached_tokens is used when input_tokens_details is missing."""
    jsonl = _jsonl({
        "usage": {
            "prompt_tokens": 400,
            "completion_tokens": 60,
            "prompt_tokens_details": {"cached_tokens": 150},
        }
    })
    _, _, cached, _ = _extract_codex_tokens(jsonl)
    assert cached == 150


def test_extract_tokens_thinking_tokens_from_output_details():
    """Reasoning tokens from completion_tokens_details."""
    jsonl = _jsonl({
        "type": "response.done",
        "response": {
            "usage": {
                "input_tokens": 100,
                "output_tokens": 50,
                "output_tokens_details": {"reasoning_tokens": 20},
            }
        }
    })
    _, _, _, thinking = _extract_codex_tokens(jsonl)
    assert thinking == 20


def test_extract_tokens_thinking_from_usage_key():
    """thinking_tokens at the usage level."""
    jsonl = _jsonl({
        "usage": {
            "prompt_tokens": 100,
            "completion_tokens": 50,
            "thinking_tokens": 15,
        }
    })
    _, _, _, thinking = _extract_codex_tokens(jsonl)
    assert thinking == 15


def test_extract_tokens_accumulates_across_events():
    """Multiple usage events are summed."""
    jsonl = _jsonl(
        {"type": "response.done", "response": {"usage": {"input_tokens": 50, "output_tokens": 20}}},
        {"type": "response.done", "response": {"usage": {"input_tokens": 30, "output_tokens": 10}}},
    )
    pt, ct, _, _ = _extract_codex_tokens(jsonl)
    assert pt == 80
    assert ct == 30


@pytest.mark.parametrize("bad_line", [
    "not json at all",
    '["this is a list"]',
    "",
    "   ",
    "// comment line",
])
def test_extract_tokens_skips_non_dict_lines(bad_line):
    """Non-dict lines are gracefully skipped."""
    jsonl = bad_line + "\n" + json.dumps({"input_tokens": 10, "output_tokens": 5})
    pt, ct, _, _ = _extract_codex_tokens(jsonl)
    assert pt == 10
    assert ct == 5


def test_extract_tokens_response_usage_type():
    """type=response.usage triggers nested extraction."""
    jsonl = _jsonl({
        "type": "response.usage",
        "response": {
            "usage": {"input_tokens": 77, "output_tokens": 33}
        }
    })
    pt, ct, _, _ = _extract_codex_tokens(jsonl)
    assert pt == 77
    assert ct == 33


def test_extract_tokens_response_completed_type():
    """type=response.completed triggers nested extraction."""
    jsonl = _jsonl({
        "type": "response.completed",
        "response": {
            "usage": {"input_tokens": 60, "output_tokens": 25}
        }
    })
    pt, ct, _, _ = _extract_codex_tokens(jsonl)
    assert pt == 60
    assert ct == 25


# ===========================================================================
# 2. _extract_codex_tool_traces
# ===========================================================================


def test_extract_traces_empty():
    """Empty input returns no traces."""
    assert _extract_codex_tool_traces("") == []


def test_extract_traces_function_call_pair():
    """function_call + function_call_output produces one trace."""
    jsonl = _jsonl(
        {"type": "function_call", "call_id": "c1", "name": "search_memory", "arguments": '{"query": "emit"}'},
        {"type": "function_call_output", "call_id": "c1", "output": '[{"key":"k1"}]'},
    )
    traces = _extract_codex_tool_traces(jsonl)
    assert len(traces) == 1
    assert traces[0].tool_name == "search_memory"
    assert traces[0].tool_args == {"query": "emit"}
    assert traces[0].roundtrip == 1
    # output is a list with 1 item, so snippet_count=1
    assert traces[0].tool_result == {"retrieved": 1}


def test_extract_traces_output_without_matching_call():
    """function_call_output with no prior call still records a trace with empty name."""
    jsonl = _jsonl(
        {"type": "function_call_output", "call_id": "orphan", "output": '"hello"'},
    )
    traces = _extract_codex_tool_traces(jsonl)
    assert len(traces) == 1
    assert traces[0].tool_name == ""


def test_extract_traces_response_output_item_added_function_call():
    """response.output_item.added with item.type=function_call records a pending call."""
    jsonl = _jsonl(
        {"type": "response.output_item.added", "item": {"type": "function_call", "call_id": "c2", "name": "get_snippet_by_key", "arguments": '{"key":"foo"}'}},
        {"type": "function_call_output", "call_id": "c2", "output": '{"code":"x"}'},
    )
    traces = _extract_codex_tool_traces(jsonl)
    assert len(traces) == 1
    assert traces[0].tool_name == "get_snippet_by_key"


def test_extract_traces_response_output_item_added_function_call_output():
    """response.output_item.added with item.type=function_call_output records result."""
    jsonl = _jsonl(
        {"type": "function_call", "call_id": "c3", "name": "read_file", "arguments": '{"path":"a.py"}'},
        {"type": "response.output_item.added", "item": {"type": "function_call_output", "call_id": "c3", "output": '"file contents"'}},
    )
    traces = _extract_codex_tool_traces(jsonl)
    assert len(traces) == 1
    assert traces[0].tool_name == "read_file"


def test_extract_traces_mcp_tool_call():
    """item.completed with type=mcp_tool_call normalizes to mcp__server__tool name."""
    jsonl = _jsonl({
        "type": "item.completed",
        "item": {
            "type": "mcp_tool_call",
            "server": "voltsnip",
            "tool": "search_memory",
            "arguments": {"query": "emit"},
            "result": [{"key": "k1"}, {"key": "k2"}],
        }
    })
    traces = _extract_codex_tool_traces(jsonl)
    assert len(traces) == 1
    assert traces[0].tool_name == "mcp__voltsnip__search_memory"
    assert traces[0].tool_args == {"query": "emit"}
    assert traces[0].tool_result == {"retrieved": 2}
    assert traces[0].roundtrip == 1


def test_extract_traces_mcp_tool_call_string_arguments():
    """mcp_tool_call with arguments as JSON string (not dict) is parsed."""
    jsonl = _jsonl({
        "type": "item.completed",
        "item": {
            "type": "mcp_tool_call",
            "server": "voltsnip",
            "tool": "get_snippet_by_key",
            "arguments": '{"key": "org_metrics_emit"}',
            "result": "some result text",
        }
    })
    traces = _extract_codex_tool_traces(jsonl)
    assert len(traces) == 1
    assert traces[0].tool_args == {"key": "org_metrics_emit"}
    # result is not a list, so raw truncated
    assert "raw" in traces[0].tool_result


def test_extract_traces_mcp_tool_call_unparseable_arguments():
    """mcp_tool_call with unparseable string arguments falls back to empty dict."""
    jsonl = _jsonl({
        "type": "item.completed",
        "item": {
            "type": "mcp_tool_call",
            "server": "voltsnip",
            "tool": "search_memory",
            "arguments": "not valid json {{",
            "result": None,
        }
    })
    traces = _extract_codex_tool_traces(jsonl)
    assert len(traces) == 1
    assert traces[0].tool_args == {}


def test_extract_traces_multiple_roundtrips():
    """Multiple tool call pairs get sequential roundtrip numbers."""
    jsonl = _jsonl(
        {"type": "function_call", "call_id": "a", "name": "tool_a", "arguments": "{}"},
        {"type": "function_call_output", "call_id": "a", "output": '"ok"'},
        {"type": "function_call", "call_id": "b", "name": "tool_b", "arguments": "{}"},
        {"type": "function_call_output", "call_id": "b", "output": '"ok"'},
    )
    traces = _extract_codex_tool_traces(jsonl)
    assert len(traces) == 2
    assert traces[0].roundtrip == 1
    assert traces[1].roundtrip == 2


def test_extract_traces_fallback_generic_call_event():
    """An event with name+arguments+call_id but no type still records as pending."""
    jsonl = _jsonl(
        {"name": "some_tool", "arguments": '{"x":1}', "call_id": "z1"},
        {"type": "function_call_output", "call_id": "z1", "output": '"done"'},
    )
    traces = _extract_codex_tool_traces(jsonl)
    assert len(traces) == 1
    assert traces[0].tool_name == "some_tool"


# ===========================================================================
# 3. _extract_codex_stream_error
# ===========================================================================


def test_stream_error_none_on_clean_output():
    """No error events returns None."""
    jsonl = _jsonl(
        {"type": "response.done", "response": {"usage": {"input_tokens": 10, "output_tokens": 5}}},
    )
    assert _extract_codex_stream_error(jsonl) is None


def test_stream_error_empty_input():
    assert _extract_codex_stream_error("") is None


def test_stream_error_type_error_with_message():
    jsonl = _jsonl({"type": "error", "message": "rate limit exceeded"})
    result = _extract_codex_stream_error(jsonl)
    assert result == "rate limit exceeded"


def test_stream_error_type_error_with_error_field():
    jsonl = _jsonl({"type": "error", "error": "server_error"})
    result = _extract_codex_stream_error(jsonl)
    assert result == "server_error"


def test_stream_error_type_error_no_message():
    """type=error with no message/error returns generic message."""
    jsonl = _jsonl({"type": "error"})
    result = _extract_codex_stream_error(jsonl)
    assert result == "codex stream returned error event"


def test_stream_error_response_failed_with_reason():
    jsonl = _jsonl({
        "type": "response.failed",
        "response": {"status_details": {"reason": "content_filter"}}
    })
    result = _extract_codex_stream_error(jsonl)
    assert result == "content_filter"


def test_stream_error_response_incomplete_with_reason():
    jsonl = _jsonl({
        "type": "response.incomplete",
        "response": {"status_details": {"reason": "max_output_tokens"}}
    })
    result = _extract_codex_stream_error(jsonl)
    assert result == "max_output_tokens"


def test_stream_error_response_failed_no_reason():
    """response.failed with no reason returns generic event type string."""
    jsonl = _jsonl({"type": "response.failed", "response": {}})
    result = _extract_codex_stream_error(jsonl)
    assert result == "codex stream: response.failed"


def test_stream_error_response_failed_with_error_fallback():
    """response.failed with no status_details but an error key at top level."""
    jsonl = _jsonl({"type": "response.failed", "error": "timeout", "response": {}})
    result = _extract_codex_stream_error(jsonl)
    assert result == "timeout"


@pytest.mark.parametrize("bad_line", [
    "not json",
    '["array"]',
    "   ",
])
def test_stream_error_skips_bad_lines(bad_line):
    """Non-dict lines are skipped gracefully."""
    combined = bad_line + "\n" + json.dumps({"type": "response.done", "response": {}})
    assert _extract_codex_stream_error(combined) is None


# ===========================================================================
# 4. CodexInvocation.cleanup
# ===========================================================================


def test_cleanup_stops_harness_server():
    """cleanup() calls stop() on the harness server."""
    mock_server = MagicMock()
    inv = CodexInvocation(
        cmd=["codex"], cwd=None, timeout=60,
        output_file=Path("/tmp/out.txt"),
        _harness_server=mock_server,
    )
    inv.cleanup()
    mock_server.stop.assert_called_once()


def test_cleanup_removes_tmp_schema(tmp_path):
    """cleanup() unlinks the tmp_schema file."""
    schema_file = tmp_path / "schema.json"
    schema_file.write_text("{}")
    inv = CodexInvocation(
        cmd=["codex"], cwd=None, timeout=60,
        output_file=Path("/tmp/out.txt"),
        _tmp_schema=str(schema_file),
    )
    inv.cleanup()
    assert not schema_file.exists()


def test_cleanup_removes_sidecar_dir(tmp_path):
    """cleanup() rmtrees the sidecar directory."""
    sidecar = tmp_path / "sidecar"
    sidecar.mkdir()
    (sidecar / "file.txt").write_text("data")
    inv = CodexInvocation(
        cmd=["codex"], cwd=None, timeout=60,
        output_file=Path("/tmp/out.txt"),
        _sidecar_dir=str(sidecar),
    )
    inv.cleanup()
    assert not sidecar.exists()


def test_cleanup_handles_missing_resources():
    """cleanup() does not raise when resources are already gone."""
    inv = CodexInvocation(
        cmd=["codex"], cwd=None, timeout=60,
        output_file=Path("/tmp/out.txt"),
        _tmp_schema="/nonexistent/schema.json",
        _sidecar_dir="/nonexistent/sidecar",
    )
    # Should not raise
    inv.cleanup()


def test_cleanup_handles_server_stop_exception():
    """cleanup() swallows exceptions from harness_server.stop()."""
    mock_server = MagicMock()
    mock_server.stop.side_effect = RuntimeError("already stopped")
    inv = CodexInvocation(
        cmd=["codex"], cwd=None, timeout=60,
        output_file=Path("/tmp/out.txt"),
        _harness_server=mock_server,
    )
    # Should not raise
    inv.cleanup()
    mock_server.stop.assert_called_once()


def test_cleanup_noop_when_no_resources():
    """cleanup() is a no-op when all resource fields are default/empty."""
    inv = CodexInvocation(
        cmd=["codex"], cwd=None, timeout=60,
        output_file=Path("/tmp/out.txt"),
    )
    # Should not raise
    inv.cleanup()


# ===========================================================================
# 5. _build_codex_invocation
# ===========================================================================


@patch("vsevals.providers.codex.HarnessMCPServer")
@patch("vsevals.providers.codex.tempfile.mkdtemp", return_value="/tmp/fake_wd")
def test_build_invocation_no_tools(mock_mkdtemp, mock_harness, tmp_path):
    """No-tools variant: no HarnessMCPServer, sandbox read-only, mcp_servers wiped."""
    cfg = _make_run_config()
    inv = _build_codex_invocation(
        model_id="gpt-5",
        combined_prompt="Fix this bug",
        cfg=cfg,
        tool_schemas=None,
        sidecar_files=None,
        timeout=120,
        run_dir=tmp_path,
    )
    assert "codex" == inv.cmd[0]
    assert "--model" in inv.cmd
    assert inv.cmd[inv.cmd.index("--model") + 1] == "gpt-5"
    assert "--sandbox" in inv.cmd
    assert "read-only" in inv.cmd
    assert "mcp_servers={}" in " ".join(inv.cmd)
    # No harness server started
    mock_harness.assert_not_called()
    assert inv._harness_server is None
    # Prompt is the last argument
    assert inv.cmd[-1] == "Fix this bug"
    inv.cleanup()


@patch("vsevals.providers.codex.HarnessMCPServer")
@patch("vsevals.providers.codex.tempfile.mkdtemp", return_value="/tmp/fake_wd")
def test_build_invocation_with_tools(mock_mkdtemp, mock_harness_cls, tmp_path):
    """Tool variant: HarnessMCPServer started, MCP URL configured in cmd."""
    mock_server_instance = MagicMock()
    mock_server_instance.port = 9876
    mock_server_instance.start.return_value = mock_server_instance
    mock_harness_cls.return_value = mock_server_instance

    cfg = _make_run_config()
    inv = _build_codex_invocation(
        model_id="gpt-5",
        combined_prompt="Fix this bug",
        cfg=cfg,
        tool_schemas=[{"name": "search_memory"}],
        sidecar_files=None,
        timeout=600,
        run_dir=tmp_path,
    )
    mock_harness_cls.assert_called_once()
    mock_server_instance.start.assert_called_once()
    assert inv._harness_server is mock_server_instance
    cmd_str = " ".join(inv.cmd)
    assert "mcp_servers.voltsnip.url=http://127.0.0.1:9876/mcp" in cmd_str
    inv.cleanup()


@patch("vsevals.providers.codex.HarnessMCPServer")
@patch("vsevals.providers.codex.tempfile.mkdtemp", return_value="/tmp/fake_wd")
def test_build_invocation_reasoning_effort(mock_mkdtemp, mock_harness, tmp_path):
    """reasoning_effort config is added to cmd."""
    cfg = _make_run_config(reasoning_effort="high")
    inv = _build_codex_invocation(
        model_id="gpt-5",
        combined_prompt="prompt",
        cfg=cfg,
        tool_schemas=None,
        sidecar_files=None,
        timeout=120,
        run_dir=tmp_path,
    )
    cmd_str = " ".join(inv.cmd)
    assert "model_reasoning_effort=high" in cmd_str
    inv.cleanup()


@patch("vsevals.providers.codex.HarnessMCPServer")
@patch("vsevals.providers.codex.tempfile.mkdtemp", return_value="/tmp/fake_wd")
def test_build_invocation_structured_output(mock_mkdtemp, mock_harness, tmp_path):
    """structured_output=True creates a tmp_schema file and adds --output-schema."""
    cfg = _make_run_config(structured_output=True)
    inv = _build_codex_invocation(
        model_id="gpt-5",
        combined_prompt="prompt",
        cfg=cfg,
        tool_schemas=None,
        sidecar_files=None,
        timeout=120,
        run_dir=tmp_path,
    )
    assert "--output-schema" in inv.cmd
    assert inv._tmp_schema  # non-empty string
    # The schema file should exist and contain valid JSON
    schema_content = json.loads(Path(inv._tmp_schema).read_text())
    assert schema_content["type"] == "object"
    assert "code" in schema_content["properties"]
    inv.cleanup()


@patch("vsevals.providers.codex.HarnessMCPServer")
@patch("vsevals.providers.codex.tempfile.mkdtemp", return_value="/tmp/fake_wd")
def test_build_invocation_sidecar_files(mock_mkdtemp, mock_harness, tmp_path):
    """Sidecar files are written to the effective cwd directory."""
    # Override mkdtemp to return a real dir we control
    real_sidecar = tmp_path / "sidecar_wd"
    real_sidecar.mkdir()
    mock_mkdtemp.return_value = str(real_sidecar)

    cfg = _make_run_config()
    inv = _build_codex_invocation(
        model_id="gpt-5",
        combined_prompt="prompt",
        cfg=cfg,
        tool_schemas=None,
        sidecar_files={"AGENTS.md": "# Agent guide", "context.txt": "some context"},
        timeout=120,
        run_dir=tmp_path,
    )
    assert (real_sidecar / "AGENTS.md").read_text() == "# Agent guide"
    assert (real_sidecar / "context.txt").read_text() == "some context"
    inv.cleanup()


@patch("vsevals.providers.codex.HarnessMCPServer")
@patch("vsevals.providers.codex.tempfile.mkdtemp", return_value="/tmp/fake_wd")
def test_build_invocation_output_file_created(mock_mkdtemp, mock_harness, tmp_path):
    """output_file is touched in run_dir and added to cmd via -o flag."""
    cfg = _make_run_config()
    inv = _build_codex_invocation(
        model_id="gpt-5",
        combined_prompt="prompt",
        cfg=cfg,
        tool_schemas=None,
        sidecar_files=None,
        timeout=120,
        run_dir=tmp_path,
    )
    assert inv.output_file.exists()
    assert "-o" in inv.cmd
    assert str(inv.output_file) in inv.cmd
    inv.cleanup()


@patch("vsevals.providers.codex.HarnessMCPServer")
@patch("vsevals.providers.codex.tempfile.mkdtemp", return_value="/tmp/fake_wd")
def test_build_invocation_cmd_has_standard_flags(mock_mkdtemp, mock_harness, tmp_path):
    """Verify standard flags: -a never, exec, --json, --ephemeral, --skip-git-repo-check."""
    cfg = _make_run_config()
    inv = _build_codex_invocation(
        model_id="gpt-5",
        combined_prompt="prompt",
        cfg=cfg,
        tool_schemas=None,
        sidecar_files=None,
        timeout=120,
        run_dir=tmp_path,
    )
    assert "exec" in inv.cmd
    assert "--json" in inv.cmd
    assert "--ephemeral" in inv.cmd
    assert "--skip-git-repo-check" in inv.cmd
    # -a never appears
    assert "-a" in inv.cmd
    idx = inv.cmd.index("-a")
    assert inv.cmd[idx + 1] == "never"
    inv.cleanup()


# ===========================================================================
# 6. _execute_codex
# ===========================================================================


@patch("vsevals.providers.codex.subprocess.run")
def test_execute_codex_success(mock_run, tmp_path):
    """Successful execution writes stdout/stderr to disk and returns CodexRawOutput."""
    output_file = tmp_path / "output.txt"
    output_file.write_text("answer text")
    mock_run.return_value = SimpleNamespace(
        returncode=0,
        stdout='{"type":"response.done","response":{"usage":{"input_tokens":10,"output_tokens":5}}}',
        stderr="",
    )
    inv = CodexInvocation(
        cmd=["codex", "exec"], cwd=str(tmp_path), timeout=60,
        output_file=output_file,
    )
    raw = _execute_codex(inv, tmp_path)
    assert raw.returncode == 0
    assert raw.stdout_path.exists()
    assert raw.stderr_path.exists()
    assert "response.done" in raw.stdout_path.read_text()


@patch("vsevals.providers.codex.subprocess.run")
def test_execute_codex_nonzero_exit(mock_run, tmp_path):
    """Non-zero exit code raises RuntimeError after writing files to disk."""
    output_file = tmp_path / "output.txt"
    output_file.touch()
    mock_run.return_value = SimpleNamespace(
        returncode=1,
        stdout="",
        stderr="Error: model not found",
    )
    inv = CodexInvocation(
        cmd=["codex", "exec"], cwd=str(tmp_path), timeout=60,
        output_file=output_file,
    )
    with pytest.raises(RuntimeError, match="codex subprocess failed"):
        _execute_codex(inv, tmp_path)
    # Files are still written before the error
    assert (tmp_path / "subprocess.stdout.codex.jsonl").exists()
    assert (tmp_path / "subprocess.stderr.codex.txt").exists()


@patch("vsevals.providers.codex.subprocess.run")
def test_execute_codex_stream_error_raises(mock_run, tmp_path):
    """Stream error in stdout with returncode=0 raises RuntimeError."""
    output_file = tmp_path / "output.txt"
    output_file.touch()
    mock_run.return_value = SimpleNamespace(
        returncode=0,
        stdout='{"type":"error","message":"rate_limit_exceeded"}',
        stderr="",
    )
    inv = CodexInvocation(
        cmd=["codex", "exec"], cwd=str(tmp_path), timeout=60,
        output_file=output_file,
    )
    with pytest.raises(RuntimeError, match="codex stream error: rate_limit_exceeded"):
        _execute_codex(inv, tmp_path)


@patch("vsevals.providers.codex.subprocess.run")
def test_execute_codex_passes_cwd_and_timeout(mock_run, tmp_path):
    """subprocess.run is called with correct cwd and timeout."""
    output_file = tmp_path / "output.txt"
    output_file.touch()
    mock_run.return_value = SimpleNamespace(returncode=0, stdout="", stderr="")
    inv = CodexInvocation(
        cmd=["codex", "exec", "prompt"], cwd="/some/dir", timeout=300,
        output_file=output_file,
    )
    _execute_codex(inv, tmp_path)
    mock_run.assert_called_once_with(
        ["codex", "exec", "prompt"],
        capture_output=True, text=True,
        timeout=300, cwd="/some/dir",
    )


# ===========================================================================
# 7. _parse_codex_output
# ===========================================================================


def test_parse_output_reads_output_file(tmp_path):
    """Primary answer is read from the output_file."""
    stdout_path = tmp_path / "subprocess.stdout.codex.jsonl"
    stderr_path = tmp_path / "subprocess.stderr.codex.txt"
    output_file = tmp_path / "codex_last_message.txt"
    stdout_path.write_text(
        json.dumps({"type": "response.done", "response": {"usage": {"input_tokens": 100, "output_tokens": 50}}})
    )
    stderr_path.write_text("")
    output_file.write_text('{"code": "def fix(): pass", "comments": "fixed"}')

    raw = CodexRawOutput(
        returncode=0,
        stdout_path=stdout_path,
        stderr_path=stderr_path,
        output_file=output_file,
        started_at=datetime.now(timezone.utc),
        finished_at=datetime.now(timezone.utc),
    )
    parsed = _parse_codex_output(raw)
    assert '"code"' in parsed.raw_text
    assert parsed.prompt_tokens == 100
    assert parsed.completion_tokens == 50


def test_parse_output_fallback_to_last_non_json_line(tmp_path):
    """When output_file is empty, falls back to last non-JSON line in stdout."""
    stdout_path = tmp_path / "subprocess.stdout.codex.jsonl"
    stderr_path = tmp_path / "subprocess.stderr.codex.txt"
    output_file = tmp_path / "codex_last_message.txt"
    stdout_path.write_text(
        json.dumps({"type": "response.done", "response": {"usage": {"input_tokens": 10, "output_tokens": 5}}})
        + "\nThe answer is 42"
    )
    stderr_path.write_text("")
    output_file.write_text("")  # empty output file

    raw = CodexRawOutput(
        returncode=0,
        stdout_path=stdout_path,
        stderr_path=stderr_path,
        output_file=output_file,
        started_at=datetime.now(timezone.utc),
        finished_at=datetime.now(timezone.utc),
    )
    parsed = _parse_codex_output(raw)
    assert parsed.raw_text == "The answer is 42"


def test_parse_output_extracts_tool_traces(tmp_path):
    """Tool traces are extracted from stdout JSONL."""
    stdout_path = tmp_path / "subprocess.stdout.codex.jsonl"
    stderr_path = tmp_path / "subprocess.stderr.codex.txt"
    output_file = tmp_path / "codex_last_message.txt"
    stdout_path.write_text(_jsonl(
        {"type": "function_call", "call_id": "c1", "name": "search_memory", "arguments": '{"query":"emit"}'},
        {"type": "function_call_output", "call_id": "c1", "output": "[]"},
        {"input_tokens": 50, "output_tokens": 20},
    ))
    stderr_path.write_text("")
    output_file.write_text("result text")

    raw = CodexRawOutput(
        returncode=0,
        stdout_path=stdout_path,
        stderr_path=stderr_path,
        output_file=output_file,
        started_at=datetime.now(timezone.utc),
        finished_at=datetime.now(timezone.utc),
    )
    parsed = _parse_codex_output(raw)
    assert len(parsed.tool_traces) == 1
    assert parsed.tool_traces[0].tool_name == "search_memory"
    assert parsed.prompt_tokens == 50


def test_parse_output_missing_output_file(tmp_path):
    """When output_file doesn't exist, raw_text falls back from stdout."""
    stdout_path = tmp_path / "subprocess.stdout.codex.jsonl"
    stderr_path = tmp_path / "subprocess.stderr.codex.txt"
    output_file = tmp_path / "codex_last_message.txt"
    stdout_path.write_text("fallback answer text")
    stderr_path.write_text("")
    # Don't create output_file

    raw = CodexRawOutput(
        returncode=0,
        stdout_path=stdout_path,
        stderr_path=stderr_path,
        output_file=output_file,
        started_at=datetime.now(timezone.utc),
        finished_at=datetime.now(timezone.utc),
    )
    parsed = _parse_codex_output(raw)
    assert parsed.raw_text == "fallback answer text"


# ===========================================================================
# 8. call_codex (orchestrator)
# ===========================================================================


@patch("vsevals.providers.codex._parse_codex_output")
@patch("vsevals.providers.codex._execute_codex")
@patch("vsevals.providers.codex._build_codex_invocation")
def test_call_codex_orchestrates_stages(mock_build, mock_exec, mock_parse, tmp_path):
    """call_codex calls build -> execute -> parse and returns LLMResult."""
    # Setup mock invocation
    output_file = tmp_path / "output.txt"
    output_file.write_text("answer")
    mock_inv = MagicMock(spec=CodexInvocation)
    mock_inv.output_file = output_file
    mock_build.return_value = mock_inv

    # Setup mock execution
    stdout_path = tmp_path / "stdout.jsonl"
    stderr_path = tmp_path / "stderr.txt"
    stdout_path.write_text("")
    stderr_path.write_text("")
    mock_raw = CodexRawOutput(
        returncode=0,
        stdout_path=stdout_path,
        stderr_path=stderr_path,
        output_file=output_file,
        started_at=datetime.now(timezone.utc),
        finished_at=datetime.now(timezone.utc),
    )
    mock_exec.return_value = mock_raw

    # Setup mock parse
    mock_parse.return_value = CodexParsed(
        raw_text='{"code": "fixed", "comments": "done"}',
        prompt_tokens=100,
        completion_tokens=50,
        cached_tokens=0,
        thinking_tokens=None,
        tool_traces=[],
    )

    cfg = _make_run_config()
    result = call_codex(
        model_id="gpt-5",
        system_prompt="You are a test assistant.",
        user_prompt="Fix the bug.",
        cfg=cfg,
        run_dir=str(tmp_path),
    )

    mock_build.assert_called_once()
    mock_exec.assert_called_once()
    mock_parse.assert_called_once()
    mock_inv.cleanup.assert_called_once()
    assert result.raw_output == '{"code": "fixed", "comments": "done"}'
    assert result.token_usage.prompt_tokens == 100
    assert result.token_usage.completion_tokens == 50
    assert result.finish_reason == "stop"


@patch("vsevals.providers.codex._execute_codex")
@patch("vsevals.providers.codex._build_codex_invocation")
def test_call_codex_cleanup_on_exception(mock_build, mock_exec, tmp_path):
    """cleanup() is called even when _execute_codex raises."""
    mock_inv = MagicMock(spec=CodexInvocation)
    mock_build.return_value = mock_inv
    mock_exec.side_effect = RuntimeError("subprocess failed")

    cfg = _make_run_config()
    with pytest.raises(RuntimeError, match="subprocess failed"):
        call_codex(
            model_id="gpt-5",
            system_prompt="sys",
            user_prompt="user",
            cfg=cfg,
            run_dir=str(tmp_path),
        )
    mock_inv.cleanup.assert_called_once()


@patch("vsevals.providers.codex._parse_codex_output")
@patch("vsevals.providers.codex._execute_codex")
@patch("vsevals.providers.codex._build_codex_invocation")
def test_call_codex_timeout_with_tools(mock_build, mock_exec, mock_parse, tmp_path):
    """When tool_schemas are provided, timeout is max(600, llm_timeout_seconds * 2)."""
    output_file = tmp_path / "output.txt"
    output_file.write_text("answer")
    mock_inv = MagicMock(spec=CodexInvocation)
    mock_inv.output_file = output_file
    mock_build.return_value = mock_inv

    stdout_path = tmp_path / "stdout.jsonl"
    stderr_path = tmp_path / "stderr.txt"
    stdout_path.write_text("")
    stderr_path.write_text("")
    mock_exec.return_value = CodexRawOutput(
        returncode=0, stdout_path=stdout_path, stderr_path=stderr_path,
        output_file=output_file,
        started_at=datetime.now(timezone.utc),
        finished_at=datetime.now(timezone.utc),
    )
    mock_parse.return_value = CodexParsed(
        raw_text="ok", prompt_tokens=0, completion_tokens=0,
        cached_tokens=0, thinking_tokens=None, tool_traces=[],
    )

    cfg = _make_run_config(llm_timeout_seconds=100)
    call_codex(
        model_id="gpt-5",
        system_prompt="sys",
        user_prompt="user",
        cfg=cfg,
        tool_schemas=[{"name": "tool"}],
        run_dir=str(tmp_path),
    )
    # timeout should be max(600, 100 * 2) = 600
    build_kwargs = mock_build.call_args[1]
    assert build_kwargs["timeout"] == 600

    # Now with higher llm_timeout_seconds
    cfg2 = _make_run_config(llm_timeout_seconds=400)
    call_codex(
        model_id="gpt-5",
        system_prompt="sys",
        user_prompt="user",
        cfg=cfg2,
        tool_schemas=[{"name": "tool"}],
        run_dir=str(tmp_path),
    )
    build_kwargs2 = mock_build.call_args[1]
    assert build_kwargs2["timeout"] == 800  # max(600, 400 * 2) = 800


@patch("vsevals.providers.codex._parse_codex_output")
@patch("vsevals.providers.codex._execute_codex")
@patch("vsevals.providers.codex._build_codex_invocation")
def test_call_codex_no_tools_uses_direct_timeout(mock_build, mock_exec, mock_parse, tmp_path):
    """Without tool_schemas, timeout is llm_timeout_seconds directly."""
    output_file = tmp_path / "output.txt"
    output_file.write_text("answer")
    mock_inv = MagicMock(spec=CodexInvocation)
    mock_inv.output_file = output_file
    mock_build.return_value = mock_inv

    stdout_path = tmp_path / "stdout.jsonl"
    stderr_path = tmp_path / "stderr.txt"
    stdout_path.write_text("")
    stderr_path.write_text("")
    mock_exec.return_value = CodexRawOutput(
        returncode=0, stdout_path=stdout_path, stderr_path=stderr_path,
        output_file=output_file,
        started_at=datetime.now(timezone.utc),
        finished_at=datetime.now(timezone.utc),
    )
    mock_parse.return_value = CodexParsed(
        raw_text="ok", prompt_tokens=0, completion_tokens=0,
        cached_tokens=0, thinking_tokens=None, tool_traces=[],
    )

    cfg = _make_run_config(llm_timeout_seconds=120)
    call_codex(
        model_id="gpt-5",
        system_prompt="sys",
        user_prompt="user",
        cfg=cfg,
        tool_schemas=None,
        run_dir=str(tmp_path),
    )
    build_kwargs = mock_build.call_args[1]
    assert build_kwargs["timeout"] == 120


@patch("vsevals.providers.codex._parse_codex_output")
@patch("vsevals.providers.codex._execute_codex")
@patch("vsevals.providers.codex._build_codex_invocation")
def test_call_codex_combines_prompts(mock_build, mock_exec, mock_parse, tmp_path):
    """call_codex combines system + user prompts with double newline."""
    output_file = tmp_path / "output.txt"
    output_file.write_text("answer")
    mock_inv = MagicMock(spec=CodexInvocation)
    mock_inv.output_file = output_file
    mock_build.return_value = mock_inv

    stdout_path = tmp_path / "stdout.jsonl"
    stderr_path = tmp_path / "stderr.txt"
    stdout_path.write_text("")
    stderr_path.write_text("")
    mock_exec.return_value = CodexRawOutput(
        returncode=0, stdout_path=stdout_path, stderr_path=stderr_path,
        output_file=output_file,
        started_at=datetime.now(timezone.utc),
        finished_at=datetime.now(timezone.utc),
    )
    mock_parse.return_value = CodexParsed(
        raw_text="ok", prompt_tokens=0, completion_tokens=0,
        cached_tokens=0, thinking_tokens=None, tool_traces=[],
    )

    cfg = _make_run_config()
    call_codex(
        model_id="gpt-5",
        system_prompt="System instructions.",
        user_prompt="User question.",
        cfg=cfg,
        run_dir=str(tmp_path),
    )
    build_kwargs = mock_build.call_args[1]
    assert build_kwargs["combined_prompt"] == "System instructions.\n\nUser question."
