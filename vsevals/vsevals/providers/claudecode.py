from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import tempfile
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from vsevals.models import RunConfig, TokenUsage, LLMResult, ToolTrace, compute_cost
from . import _parse_payload, _int_or_none

LOGGER = logging.getLogger(__name__)


# ── Pure stream parser ──────────────────────────────────────────────────────

def _parse_claudecode_stream_json(stdout: str) -> tuple[str, int, int, int, int | None, str | None, list[ToolTrace]]:
    final_output = ""
    sys_prompt_tokens = 0
    sys_comp_tokens = 0
    sys_cached_tokens = 0
    sys_thinking_tokens: int | None = None
    session_id = None
    tool_traces: list[ToolTrace] = []

    active_call = None
    t0_call = 0.0

    for line in stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            evt = json.loads(line)
        except Exception:
            continue

        if evt.get("type") == "messageStart":
            usage = evt.get("message", {}).get("usage", {})
            sys_prompt_tokens += usage.get("input_tokens", 0)
            c_read = usage.get("cache_read_input_tokens")
            if c_read is not None:
                sys_cached_tokens += int(c_read)
            t_tok = usage.get("thinking_tokens") or usage.get("reasoning_tokens")
            if t_tok:
                sys_thinking_tokens = (sys_thinking_tokens or 0) + int(t_tok)

        elif evt.get("type") == "toolUse":
            name = evt.get("name", "")
            call_id = evt.get("id", "")
            raw_input = evt.get("input", {})
            t0_call = time.perf_counter()
            active_call = {
                "id": call_id,
                "name": name,
                "input": raw_input,
                "started_at": datetime.now(timezone.utc),
                "t0": t0_call,
            }

        elif evt.get("type") == "toolResult":
            if active_call and active_call["id"] == evt.get("toolUseId"):
                error_msg = evt.get("error")
                result_content = evt.get("content", [])
                result_str = ""
                snippet_count = None

                if isinstance(result_content, list):
                    for b in result_content:
                        if isinstance(b, dict) and b.get("type") == "text":
                            result_str += str(b.get("text", ""))
                    if not error_msg:
                        try:
                            parsed_res = json.loads(result_str)
                            if isinstance(parsed_res, list):
                                snippet_count = len(parsed_res)
                        except Exception:
                            pass

                duration = int((time.perf_counter() - active_call["t0"]) * 1000)
                tool_traces.append(ToolTrace(
                    roundtrip=len(tool_traces) + 1,
                    tool_name=active_call["name"],
                    tool_call_id=active_call["id"],
                    tool_args=active_call["input"],
                    tool_result={"retrieved": snippet_count} if snippet_count is not None else {"raw": result_str[:200]},
                    error=str(error_msg) if error_msg else None,
                    started_at=active_call["started_at"],
                    finished_at=datetime.now(timezone.utc),
                    duration_ms=duration,
                ))
            active_call = None

        elif evt.get("type") == "messageEnd":
            msg = evt.get("message", {})
            sys_comp_tokens += msg.get("usage", {}).get("output_tokens", 0)
            if not final_output and isinstance(msg.get("content"), list):
                texts = [b.get("text", "") for b in msg["content"] if b.get("type") == "text"]
                if texts:
                    final_output = "\n".join(t for t in texts if t)

        elif evt.get("type") == "text":
            final_output += evt.get("text", "")

        elif evt.get("type") == "result" and evt.get("subtype") == "success":
            # Primary output in stream-json mode — the full assistant reply.
            if not final_output:
                final_output = evt.get("result", "")

        elif "sessionId" in evt and not session_id:
            session_id = evt["sessionId"]

    if active_call:
        tool_traces.append(ToolTrace(
            roundtrip=len(tool_traces) + 1,
            tool_name=active_call["name"],
            tool_call_id=active_call.get("id"),
            tool_args=active_call["input"],
            tool_result=None,
            error="no tool result received",
            started_at=active_call.get("started_at", datetime.now(timezone.utc)),
            finished_at=datetime.now(timezone.utc),
            duration_ms=None,
        ))

    return final_output, sys_prompt_tokens, sys_comp_tokens, sys_cached_tokens, sys_thinking_tokens, session_id, tool_traces


# ── Pipeline stage outputs ──────────────────────────────────────────────────

@dataclass
class ClaudeCodeInvocation:
    """Stage 1 — everything needed to launch the claudecode subprocess."""
    cmd: list[str]
    env: dict[str, str]
    cwd: str | None
    timeout: float
    # temp resources created during build; released by cleanup()
    _mcp_config_path: str = field(default="", repr=False)
    _sidecar_dir: str = field(default="", repr=False)
    _debug_file_path: str = field(default="", repr=False)

    def cleanup(self) -> None:
        for path in (self._mcp_config_path, self._debug_file_path):
            if path:
                try:
                    os.unlink(path)
                except OSError:
                    pass
        if self._sidecar_dir:
            shutil.rmtree(self._sidecar_dir, ignore_errors=True)


@dataclass
class ClaudeCodeRawOutput:
    """Stage 2 — subprocess result; stdout/stderr persisted to disk."""
    returncode: int
    stdout_path: Path   # on-disk JSONL event stream
    stderr_path: Path   # on-disk stderr text
    started_at: datetime
    finished_at: datetime


@dataclass
class ClaudeCodeParsed:
    """Stage 3 — structured data extracted from the on-disk JSONL."""
    raw_text: str
    prompt_tokens: int
    completion_tokens: int
    cached_tokens: int
    thinking_tokens: int | None
    session_id: str | None
    tool_traces: list[ToolTrace]


# ── Stage 1: Build invocation ───────────────────────────────────────────────

def _build_claudecode_invocation(
    *,
    model_id: str,
    combined_prompt: str,
    cfg: RunConfig,
    tool_schemas: list[dict] | None,
    sidecar_files: dict[str, str] | None,
    timeout: float,
) -> ClaudeCodeInvocation:
    """Assemble cmd, env, and temp resources; nothing is executed here."""
    # Tool allowlist — prevents globally-configured MCP servers (e.g. AWS Marketplace,
    # Sheet Music, etc.) from leaking into eval runs.
    _VOLTSNIP_TOOLS = "mcp__voltsnip__search_snippets,mcp__voltsnip__get_snippet_by_canonical_key"
    allowed_tools = _VOLTSNIP_TOOLS if tool_schemas else ""

    cmd = [
        "claude", "-p", combined_prompt,
        "--dangerously-skip-permissions",
        "--output-format", "stream-json",
        "--verbose",
        "--model", model_id,
        "--allowedTools", allowed_tools,
    ]

    mcp_config_path = ""
    if tool_schemas:
        base_url = (cfg.voltsnip_base_url or "http://localhost:8011").rstrip("/")
        mcp_conf = {
            "mcpServers": {
                "voltsnip": {
                    "type": "http",
                    "url": f"{base_url}/mcp",
                }
            }
        }
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(mcp_conf, f)
            mcp_config_path = f.name
        cmd.extend(["--mcp-config", mcp_config_path])

    sidecar_dir = ""
    if sidecar_files:
        sidecar_dir = tempfile.mkdtemp(prefix="vsevals_claudecode_wd_")
        for filename, content in sidecar_files.items():
            (Path(sidecar_dir) / filename).write_text(content, encoding="utf-8")

    env = os.environ.copy()
    env.pop("CLAUDECODE", None)  # prevent "nested session" rejection when launched from within Claude Code
    env["NO_COLOR"] = "1"
    if "CLAUDE_MODEL" not in env:
        env["CLAUDE_MODEL"] = model_id

    debug_file_path = ""
    if LOGGER.isEnabledFor(logging.DEBUG):
        sf = tempfile.NamedTemporaryFile(
            mode="w", suffix=".log", prefix="vsevals_claudecode_debug_", delete=False
        )
        sf.close()
        debug_file_path = sf.name
        cmd.extend(["--debug-file", debug_file_path])

    LOGGER.debug(
        "claudecode invocation model=%s sidecar=%s debug=%s",
        model_id, bool(sidecar_dir), debug_file_path or None,
    )
    return ClaudeCodeInvocation(
        cmd=cmd, env=env,
        cwd=sidecar_dir or None,
        timeout=timeout,
        _mcp_config_path=mcp_config_path,
        _sidecar_dir=sidecar_dir,
        _debug_file_path=debug_file_path,
    )


# ── Stage 2: Execute + persist to disk ─────────────────────────────────────

def _execute_claudecode(inv: ClaudeCodeInvocation, run_dir: Path) -> ClaudeCodeRawOutput:
    """Run subprocess; write stdout/stderr to disk before anything else."""
    started_at = datetime.now(timezone.utc)
    proc = subprocess.run(
        inv.cmd, capture_output=True, text=True,
        stdin=subprocess.DEVNULL,
        timeout=inv.timeout, cwd=inv.cwd, env=inv.env,
    )
    finished_at = datetime.now(timezone.utc)

    # Persist to disk immediately — before error-checking or parsing.
    stdout_path = run_dir / "subprocess.stdout.claudecode.jsonl"
    stderr_path = run_dir / "subprocess.stderr.claudecode.txt"
    stdout_path.write_text(proc.stdout or "", encoding="utf-8")
    stderr_path.write_text(proc.stderr or "", encoding="utf-8")

    if inv._debug_file_path:
        try:
            debug_text = Path(inv._debug_file_path).read_text(encoding="utf-8", errors="replace")
            if debug_text.strip():
                LOGGER.debug("claudecode debug log:\n%s", debug_text)
        except OSError:
            pass

    if proc.returncode != 0 and not (proc.stdout or "").strip():
        raise RuntimeError(f"claude failed (exit {proc.returncode}): {proc.stderr}")

    return ClaudeCodeRawOutput(
        returncode=proc.returncode,
        stdout_path=stdout_path,
        stderr_path=stderr_path,
        started_at=started_at,
        finished_at=finished_at,
    )


# ── Stage 3: Parse from disk ────────────────────────────────────────────────

def _parse_claudecode_output(raw: ClaudeCodeRawOutput) -> ClaudeCodeParsed:
    """Read the on-disk JSONL and extract tokens, traces, and final text."""
    stdout_text = raw.stdout_path.read_text(encoding="utf-8", errors="replace")
    raw_text, pt, ct, cached, thinking, session_id, tool_traces = _parse_claudecode_stream_json(stdout_text)
    return ClaudeCodeParsed(
        raw_text=raw_text,
        prompt_tokens=pt,
        completion_tokens=ct,
        cached_tokens=cached,
        thinking_tokens=thinking,
        session_id=session_id,
        tool_traces=tool_traces,
    )


# ── Orchestrator ────────────────────────────────────────────────────────────

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
) -> LLMResult:
    timeout = max(600, cfg.llm_timeout_seconds * 2) if tool_schemas else cfg.llm_timeout_seconds
    t0 = datetime.now(timezone.utc)
    perf0 = time.perf_counter()

    # Always have a run_dir so the pipeline can write to disk.
    _tmp_run_dir = ""
    if run_dir:
        rd = Path(run_dir)
    else:
        _tmp_run_dir = tempfile.mkdtemp(prefix="vsevals_claudecode_run_")
        rd = Path(_tmp_run_dir)

    combined_prompt = f"{system_prompt}\n\n{user_prompt}".strip()
    inv = _build_claudecode_invocation(
        model_id=model_id, combined_prompt=combined_prompt,
        cfg=cfg, tool_schemas=tool_schemas,
        sidecar_files=sidecar_files, timeout=timeout,
    )

    raw_stdout = raw_stderr = ""
    try:
        # Stage 2 → Stage 3: execute writes to disk, parse reads from disk.
        sub = _execute_claudecode(inv, rd)
        parsed = _parse_claudecode_output(sub)
        # Read artifact content before any potential cleanup below.
        raw_stdout = sub.stdout_path.read_text(encoding="utf-8", errors="replace")
        raw_stderr = sub.stderr_path.read_text(encoding="utf-8", errors="replace")
    finally:
        inv.cleanup()
        if _tmp_run_dir:
            shutil.rmtree(_tmp_run_dir, ignore_errors=True)

    result_parsed, fallback = _parse_payload(parsed.raw_text, cfg.structured_output)
    return LLMResult(
        raw_output=parsed.raw_text,
        parsed_output=result_parsed,
        token_usage=TokenUsage(
            prompt_tokens=parsed.prompt_tokens,
            completion_tokens=parsed.completion_tokens,
            total_tokens=parsed.prompt_tokens + parsed.completion_tokens,
            cached_tokens=parsed.cached_tokens,
            thinking_tokens=parsed.thinking_tokens,
            cost_usd=compute_cost(
                model_id, parsed.prompt_tokens, parsed.completion_tokens, parsed.cached_tokens
            ),
        ),
        structured_output_attempted=cfg.structured_output,
        structured_output_succeeded=not fallback if cfg.structured_output else False,
        fallback_parser_used=fallback,
        request_started_at=t0,
        request_finished_at=datetime.now(timezone.utc),
        request_latency_ms=int((time.perf_counter() - perf0) * 1000),
        request_id=parsed.session_id,
        finish_reason="stop",
        tool_traces=parsed.tool_traces,
        subprocess_stdout=raw_stdout,
        subprocess_stderr=raw_stderr,
    )
