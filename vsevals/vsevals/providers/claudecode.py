from __future__ import annotations

import json
import logging
import os
import shlex
import shutil
import subprocess
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

from vsevals.models import RunConfig, TokenUsage, LLMResult, ToolTrace, compute_cost
from . import _parse_payload, _int_or_none

LOGGER = logging.getLogger(__name__)


def _extract_snippet_count(result_str: str) -> int | None:
    """Try to parse a snippet count from a tool result string."""
    try:
        parsed = json.loads(result_str)
        if isinstance(parsed, dict) and "result" in parsed:
            parsed = parsed["result"]
        if isinstance(parsed, list):
            return len(parsed)
    except Exception:
        pass
    return None


def _extract_stream_error(stdout: str) -> str | None:
    """Return a terminal stream error message when claudecode reports one.

    ClaudeCode can exit with returncode=0 while still marking the terminal
    stream result as an error (`{"type":"result", "is_error": true, ...}`).
    Those runs must be treated as provider failures so they are not persisted
    as status=ok with empty parsed output.
    """
    assistant_error: str | None = None
    for line in stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            evt = json.loads(line)
        except Exception:
            continue
        if not isinstance(evt, dict):
            continue

        etype = evt.get("type")
        if etype == "assistant":
            # Best-effort fallback if the stream has an assistant error marker.
            err = evt.get("error")
            if err and not assistant_error:
                assistant_error = str(err)
        elif etype == "result" and bool(evt.get("is_error")):
            msg = evt.get("result") or evt.get("error") or assistant_error
            return str(msg) if msg else "claudecode stream returned is_error=true"

    return assistant_error


def _parse_claudecode_stream_json(stdout: str) -> tuple[str, int, int, int, int | None, str | None, list[ToolTrace]]:
    final_output = ""
    sys_prompt_tokens = sys_comp_tokens = sys_cached_tokens = 0
    sys_thinking_tokens: int | None = None
    session_id = None
    tool_traces: list[ToolTrace] = []
    active_calls: dict[str, dict] = {}

    def _close_call(call: dict, rc: object, error_msg: object) -> None:
        result_str = ""
        if isinstance(rc, list):
            result_str = "".join(str(b.get("text", "")) for b in rc if isinstance(b, dict) and b.get("type") == "text")
        elif isinstance(rc, str):
            result_str = rc
        sc = None if error_msg else _extract_snippet_count(result_str)
        tool_traces.append(ToolTrace(
            roundtrip=len(tool_traces) + 1, tool_name=call["name"], tool_call_id=call.get("id"),
            tool_args=call["input"],
            tool_result={"retrieved": sc} if sc is not None else {"raw": result_str[:200]},
            error=str(error_msg) if error_msg else None,
            started_at=call.get("started_at", datetime.now(timezone.utc)),
            finished_at=datetime.now(timezone.utc),
            duration_ms=int((time.perf_counter() - call["t0"]) * 1000),
        ))
    seen_msg_ids: set[str] = set()

    for line in stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            evt = json.loads(line)
        except Exception:
            LOGGER.debug("claudecode stream: dropped non-JSON line: %r", line[:200])
            continue

        etype = evt.get("type")

        if etype == "system" and evt.get("subtype") == "init":
            if not session_id:
                session_id = evt.get("session_id") or evt.get("sessionId")

        elif etype == "assistant":
            msg = evt.get("message", {})
            msg_id = msg.get("id", "")
            if msg_id not in seen_msg_ids:
                seen_msg_ids.add(msg_id)
                usage = msg.get("usage", {})
                sys_prompt_tokens += usage.get("input_tokens", 0) or 0
                sys_comp_tokens += usage.get("output_tokens", 0) or 0
                cached = usage.get("cache_read_input_tokens") or usage.get("cached_tokens")
                if cached:
                    sys_cached_tokens += int(cached)
                t_tok = usage.get("thinking_tokens") or usage.get("reasoning_tokens")
                if t_tok:
                    sys_thinking_tokens = (sys_thinking_tokens or 0) + int(t_tok)
            for block in msg.get("content", []):
                btype = block.get("type")
                if btype == "tool_use":
                    call_id = block.get("id", "")
                    if call_id not in active_calls:
                        active_calls[call_id] = {
                            "id": call_id,
                            "name": block.get("name", ""),
                            "input": block.get("input", {}),
                            "started_at": datetime.now(timezone.utc),
                            "t0": time.perf_counter(),
                        }
                elif btype == "text":
                    if text := block.get("text", ""):
                        if text.strip():
                            final_output = text

        elif etype == "user":
            msg = evt.get("message", {})
            for block in msg.get("content", []):
                if block.get("type") == "tool_result":
                    if call := active_calls.pop(block.get("tool_use_id", ""), None):
                        _close_call(call, block.get("content", ""), block.get("error"))

        elif etype == "messageStart":
            usage = evt.get("message", {}).get("usage", {})
            sys_prompt_tokens += usage.get("input_tokens", 0)
            c_read = usage.get("cache_read_input_tokens")
            if c_read is not None:
                sys_cached_tokens += int(c_read)
            t_tok = usage.get("thinking_tokens") or usage.get("reasoning_tokens")
            if t_tok:
                sys_thinking_tokens = (sys_thinking_tokens or 0) + int(t_tok)

        elif etype == "toolUse":
            call_id = evt.get("id", "")
            if call_id not in active_calls:
                active_calls[call_id] = {
                    "id": call_id,
                    "name": evt.get("name", ""),
                    "input": evt.get("input", {}),
                    "started_at": datetime.now(timezone.utc),
                    "t0": time.perf_counter(),
                }

        elif etype == "toolResult":
            if call := active_calls.pop(evt.get("toolUseId", ""), None):
                _close_call(call, evt.get("content", []), evt.get("error"))

        elif etype == "messageEnd":
            msg = evt.get("message", {})
            sys_comp_tokens += msg.get("usage", {}).get("output_tokens", 0)
            if not final_output and isinstance(msg.get("content"), list):
                texts = [b.get("text", "") for b in msg["content"] if b.get("type") == "text"]
                if texts:
                    final_output = "\n".join(t for t in texts if t)

        elif etype == "text":
            final_output += evt.get("text", "")

        elif etype == "result" and evt.get("subtype") == "success":
            if not final_output:
                final_output = evt.get("result", "")

        if not session_id:
            session_id = evt.get("session_id") or evt.get("sessionId")

    for call in active_calls.values():
        _close_call(call, [], "no tool result received")

    return final_output, sys_prompt_tokens, sys_comp_tokens, sys_cached_tokens, sys_thinking_tokens, session_id, tool_traces


def call_claudecode(
    *,
    model_id: str,
    system_prompt: str,
    user_prompt: str,
    cfg: RunConfig,
    tool_schemas: list[dict] | None = None,
    max_tool_turns: int = 8,
    sidecar_files: dict[str, str] | None = None,
    run_dir: str | None = None,
    repo_root: str | None = None,
) -> LLMResult:
    timeout = max(600, cfg.llm_timeout_seconds * 2) if tool_schemas else cfg.llm_timeout_seconds
    t0 = datetime.now(timezone.utc)
    perf0 = time.perf_counter()

    _tmp_run_dir = ""
    rd = Path(run_dir) if run_dir else Path(_tmp_run_dir := tempfile.mkdtemp(prefix="vsevals_claudecode_run_"))

    combined_prompt = f"{system_prompt}\n\n{user_prompt}".strip()

    _VOLTSNIP_TOOLS = [
        "mcp__voltsnip__search_memory",
        "mcp__voltsnip__get_snippet_by_canonical_key",
        "mcp__voltsnip__semantic_search_api_v1_search_semantic_get",
        "mcp__voltsnip__search_api_v1_search",
        "mcp__voltsnip__read_snippet_api_v1_snippets",
        "mcp__voltsnip__read_snippet_by_canonical_key_api_v1_snippets_by_key",
        "mcp__voltsnip__view_snippet_api_v1_snippets",
    ]
    _DISALLOWED_TOOLS = [
        "Bash", "Edit", "Write", "NotebookEdit", "WebFetch", "WebSearch", "TodoWrite",
        "Task", "TaskOutput", "TaskStop", "AskUserQuestion", "Skill",
        "EnterPlanMode", "ExitPlanMode", "EnterWorktree",
        "ReadMcpResourceTool", "ListMcpResourcesTool",
    ]
    has_plugin_skills = any(k.startswith("skills/") for k in (sidecar_files or {}))

    if tool_schemas:
        skill_tools = ["Skill"] if has_plugin_skills else []
        allowed_tools = ",".join(_VOLTSNIP_TOOLS + skill_tools)
        disallowed_tools = ",".join(t for t in _DISALLOWED_TOOLS if not (has_plugin_skills and t == "Skill"))
    else:
        allowed_tools = ""
        disallowed_tools = ",".join(_DISALLOWED_TOOLS)

    cmd = [
        "claude", "-p", combined_prompt,
        "--dangerously-skip-permissions",
        "--output-format", "stream-json",
        "--verbose",
        "--model", model_id,
        "--allowedTools", allowed_tools,
        "--disallowedTools", disallowed_tools,
    ]
    if cfg.reasoning_effort:
        cmd.extend(["--effort", cfg.reasoning_effort])

    mcp_config_path = ""
    if tool_schemas:
        base_url = (cfg.voltsnip_base_url or "http://localhost:8000").rstrip("/")
        mcp_conf = {"mcpServers": {"voltsnip": {"type": "http", "url": f"{base_url}/mcp"}}}
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(mcp_conf, f)
            mcp_config_path = f.name
        cmd.extend(["--mcp-config", mcp_config_path])

    _ = repo_root  # kept in signature for call-site stability
    sidecar_dir = tempfile.mkdtemp(prefix="vsevals_claudecode_wd_")
    if sidecar_files:
        for filename, content in sidecar_files.items():
            dest = Path(sidecar_dir) / filename
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text(content, encoding="utf-8")
    if has_plugin_skills:
        cmd.extend(["--plugin-dir", str(Path(sidecar_dir) / "skills")])

    env = os.environ.copy()
    env.pop("CLAUDECODE", None)
    env["NO_COLOR"] = "1"
    if "CLAUDE_MODEL" not in env:
        env["CLAUDE_MODEL"] = model_id

    debug_file_path = ""
    if LOGGER.isEnabledFor(logging.DEBUG):
        sf = tempfile.NamedTemporaryFile(mode="w", suffix=".log", prefix="vsevals_claudecode_debug_", delete=False)
        sf.close()
        debug_file_path = sf.name
        cmd.extend(["--debug-file", debug_file_path])

    LOGGER.debug("claudecode invocation model=%s sidecar=%s cwd=%s", model_id, bool(sidecar_files), sidecar_dir)

    raw_stdout = raw_stderr = ""
    try:
        started_at = datetime.now(timezone.utc)
        proc = subprocess.run(
            cmd, capture_output=True, text=True,
            stdin=subprocess.DEVNULL, timeout=timeout, cwd=sidecar_dir, env=env,
        )

        stdout_path = rd / "subprocess.stdout.claudecode.jsonl"
        stderr_path = rd / "subprocess.stderr.claudecode.txt"
        stdout_path.write_text(proc.stdout or "", encoding="utf-8")
        stderr_path.write_text(proc.stderr or "", encoding="utf-8")

        _env_lines = "\n".join(
            f"export {k}={shlex.quote(v)}" for k, v in env.items()
            if k in ("NO_COLOR", "CLAUDE_MODEL", "ANTHROPIC_API_KEY")
        )
        cmd_path = rd / "subprocess.cmd.claudecode.sh"
        cmd_path.write_text(
            "#!/usr/bin/env bash\n# Auto-generated — reproduces the exact claudecode subprocess invocation.\n"
            f"cd {shlex.quote(sidecar_dir)}\n"
            + (_env_lines + "\n" if _env_lines else "")
            + "exec " + shlex.join(cmd) + "\n",
            encoding="utf-8",
        )
        cmd_path.chmod(0o755)

        if debug_file_path:
            try:
                debug_text = Path(debug_file_path).read_text(encoding="utf-8", errors="replace")
                if debug_text.strip():
                    LOGGER.debug("claudecode debug log:\n%s", debug_text)
            except OSError:
                pass

        if proc.returncode != 0 and not (proc.stdout or "").strip():
            raise RuntimeError(f"claude failed (exit {proc.returncode}): {proc.stderr}")

        raw_stdout = stdout_path.read_text(encoding="utf-8", errors="replace")
        raw_stderr = stderr_path.read_text(encoding="utf-8", errors="replace")

        stream_error = _extract_stream_error(raw_stdout)
        if stream_error:
            raise RuntimeError(f"claudecode stream error: {stream_error}")

    finally:
        for path in (mcp_config_path, debug_file_path):
            if path:
                try:
                    os.unlink(path)
                except OSError:
                    pass
        shutil.rmtree(sidecar_dir, ignore_errors=True)
        if _tmp_run_dir:
            shutil.rmtree(_tmp_run_dir, ignore_errors=True)

    raw_text, pt, ct, cached, thinking, session_id, tool_traces = _parse_claudecode_stream_json(raw_stdout)

    result_parsed, fallback = _parse_payload(raw_text, cfg.structured_output)
    return LLMResult(
        raw_output=raw_text,
        parsed_output=result_parsed,
        token_usage=TokenUsage(
            prompt_tokens=pt,
            completion_tokens=ct,
            total_tokens=pt + ct,
            cached_tokens=cached,
            thinking_tokens=thinking,
            cost_usd=compute_cost(model_id, pt, ct, cached),
        ),
        structured_output_attempted=cfg.structured_output,
        structured_output_succeeded=not fallback if cfg.structured_output else False,
        fallback_parser_used=fallback,
        request_started_at=t0,
        request_finished_at=datetime.now(timezone.utc),
        request_latency_ms=int((time.perf_counter() - perf0) * 1000),
        request_id=session_id,
        finish_reason="stop",
        tool_traces=tool_traces,
        subprocess_stdout=raw_stdout,
        subprocess_stderr=raw_stderr,
    )
