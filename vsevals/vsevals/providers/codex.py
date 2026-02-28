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


# ── Pure token/trace parsers ────────────────────────────────────────────────

def _extract_codex_tokens(jsonl_text: str) -> tuple[int, int, int, int | None]:
    total_pt = 0
    total_ct = 0
    total_cached = 0
    last_thinking: int | None = None

    for line in jsonl_text.splitlines():
        line = line.strip()
        if not line or not line.startswith("{"):
            continue
        try:
            obj = json.loads(line)
        except Exception:
            continue
        if not isinstance(obj, dict):
            continue

        resp_obj = obj.get("response") if obj.get("type") in (
            "response.done", "response.completed", "response.usage"
        ) else None
        nested_usage: dict = (resp_obj or {}).get("usage") or {} if resp_obj else {}
        flat_usage: dict = obj.get("usage") or {}
        usage = nested_usage or flat_usage

        pt = (
            usage.get("input_tokens")
            or usage.get("prompt_tokens")
            or obj.get("input_tokens")
            or obj.get("prompt_tokens")
            or 0
        )
        ct = (
            usage.get("output_tokens")
            or usage.get("completion_tokens")
            or obj.get("output_tokens")
            or obj.get("completion_tokens")
            or 0
        )

        if pt or ct:
            total_pt += int(pt or 0)
            total_ct += int(ct or 0)

            in_details = (
                usage.get("input_tokens_details")
                or usage.get("prompt_tokens_details")
                or obj.get("prompt_tokens_details")
                or {}
            )
            cached_tok = in_details.get("cached_tokens", 0)
            if cached_tok:
                total_cached += int(cached_tok)

            ct_details = (
                usage.get("output_tokens_details")
                or usage.get("completion_tokens_details")
                or obj.get("completion_tokens_details")
                or {}
            )
            tt = _int_or_none(
                ct_details.get("reasoning_tokens")
                or usage.get("thinking_tokens")
                or usage.get("reasoning_tokens")
                or obj.get("thinking_tokens")
                or obj.get("reasoning_tokens")
            )
            if tt is not None:
                last_thinking = (last_thinking or 0) + tt

    return total_pt, total_ct, total_cached, last_thinking if last_thinking else None


def _extract_codex_tool_traces(jsonl_text: str) -> list[ToolTrace]:
    traces: list[ToolTrace] = []
    pending: dict[str, dict] = {}

    def _record_call(call_id: str, name: str, arguments: str) -> None:
        pending[call_id] = {
            "name": name,
            "args_raw": arguments,
            "started_at": datetime.now(timezone.utc),
            "t0": time.perf_counter(),
        }

    def _record_result(call_id: str, output: str) -> None:
        call = pending.pop(call_id, None)
        try:
            args = json.loads((call or {}).get("args_raw") or "{}")
        except Exception:
            args = {}
        try:
            result_obj = json.loads(output) if output else None
        except Exception:
            result_obj = None
        snippet_count = len(result_obj) if isinstance(result_obj, list) else None
        started_at = (call or {}).get("started_at", datetime.now(timezone.utc))
        t0_call = (call or {}).get("t0", time.perf_counter())
        traces.append(ToolTrace(
            roundtrip=len(traces) + 1,
            tool_name=(call or {}).get("name", ""),
            tool_args=args,
            tool_result={"retrieved": snippet_count} if snippet_count is not None else {"raw": str(output)[:200]},
            error=None,
            started_at=started_at,
            finished_at=datetime.now(timezone.utc),
            duration_ms=int((time.perf_counter() - t0_call) * 1000),
        ))

    for line in jsonl_text.splitlines():
        line = line.strip()
        if not line or not line.startswith("{"):
            continue
        try:
            obj = json.loads(line)
        except Exception:
            continue
        if not isinstance(obj, dict):
            continue

        evt = obj.get("type", "")

        if evt == "function_call":
            _record_call(obj.get("call_id", ""), obj.get("name", ""), obj.get("arguments", "{}"))
        elif evt == "function_call_output":
            _record_result(obj.get("call_id", ""), obj.get("output", ""))
        elif evt == "response.output_item.added":
            item = obj.get("item") or {}
            if item.get("type") == "function_call":
                _record_call(item.get("call_id", ""), item.get("name", ""), item.get("arguments", "{}"))
            elif item.get("type") == "function_call_output":
                _record_result(item.get("call_id", ""), item.get("output", ""))
        elif evt == "item.completed":
            item = obj.get("item") or {}
            if item.get("type") == "mcp_tool_call":
                server = item.get("server", "unknown")
                tool = item.get("tool", "unknown")
                tool_name = f"{server}.{tool}"
                raw_args = item.get("arguments") or {}
                if isinstance(raw_args, str):
                    try:
                        raw_args = json.loads(raw_args)
                    except Exception:
                        raw_args = {}
                raw_result = item.get("result")
                result_str = json.dumps(raw_result) if raw_result is not None else ""
                snippet_count = len(raw_result) if isinstance(raw_result, list) else None
                tool_result_payload = (
                    {"retrieved": snippet_count} if snippet_count is not None
                    else {"raw": result_str[:200]}
                )
                traces.append(ToolTrace(
                    roundtrip=len(traces) + 1,
                    tool_name=tool_name,
                    tool_args=raw_args,
                    tool_result=tool_result_payload,
                    error=None,
                    started_at=datetime.now(timezone.utc),
                    finished_at=datetime.now(timezone.utc),
                    duration_ms=0,
                ))
        elif "name" in obj and "arguments" in obj and "call_id" in obj:
            _record_call(obj["call_id"], obj["name"], obj["arguments"])

    return traces


# ── Pipeline stage outputs ──────────────────────────────────────────────────

@dataclass
class CodexInvocation:
    """Stage 1 — everything needed to launch the codex subprocess."""
    cmd: list[str]
    cwd: str | None
    timeout: float
    output_file: Path   # codex writes its final answer here (-o flag)
    # temp resources created during build; released by cleanup()
    _tmp_schema: str = field(default="", repr=False)
    _sidecar_dir: str = field(default="", repr=False)

    def cleanup(self) -> None:
        if self._tmp_schema:
            try:
                Path(self._tmp_schema).unlink(missing_ok=True)
            except Exception:
                pass
        if self._sidecar_dir:
            shutil.rmtree(self._sidecar_dir, ignore_errors=True)


@dataclass
class CodexRawOutput:
    """Stage 2 — subprocess result; stdout/stderr persisted to disk."""
    returncode: int
    stdout_path: Path   # on-disk JSONL event stream (tokens + traces)
    stderr_path: Path   # on-disk stderr text
    output_file: Path   # codex -o target (the final answer text)
    started_at: datetime
    finished_at: datetime


@dataclass
class CodexParsed:
    """Stage 3 — structured data extracted from the on-disk files."""
    raw_text: str
    prompt_tokens: int
    completion_tokens: int
    cached_tokens: int
    thinking_tokens: int | None
    tool_traces: list[ToolTrace]


# ── Stage 1: Build invocation ───────────────────────────────────────────────

def _build_codex_invocation(
    *,
    model_id: str,
    combined_prompt: str,
    cfg: RunConfig,
    tool_schemas: list[dict] | None,
    sidecar_files: dict[str, str] | None,
    timeout: float,
    run_dir: Path,
) -> CodexInvocation:
    """Assemble cmd and temp resources; nothing is executed here."""
    extra_args: list[str] = []
    if tool_schemas:
        # Tool variants: configure VoltSnip MCP only.
        base_url = (cfg.voltsnip_base_url or "http://localhost:8011").rstrip("/")
        extra_args.extend([
            "-c", "mcp_servers.voltsnip.command=curl",
            "-c", f"mcp_servers.voltsnip.args=-sNX,POST,{base_url}/mcp/messages",
            "--dangerously-bypass-approvals-and-sandbox",
        ])
    else:
        # No-tools variants: wipe any globally-configured MCP servers so they
        # don't leak into eval runs (codex has no --allowed-tools flag; -c override
        # is the only mechanism).
        extra_args.extend(["-c", "mcp_servers={}"])

    # codex writes its final answer to this file (-o flag)
    output_file = run_dir / "codex_last_message.txt"
    output_file.touch()

    tmp_schema = ""
    if cfg.structured_output:
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", prefix="vsevals_codex_schema_", delete=False
        ) as sf:
            json.dump(
                {
                    "type": "object",
                    "properties": {
                        "code": {"type": "string"},
                        "comments": {"type": "string"},
                    },
                    "required": ["code", "comments"],
                    "additionalProperties": False,
                },
                sf,
            )
            tmp_schema = sf.name

    sidecar_dir = ""
    if sidecar_files:
        sidecar_dir = tempfile.mkdtemp(prefix="vsevals_codex_wd_")
        for filename, content in sidecar_files.items():
            (Path(sidecar_dir) / filename).write_text(content, encoding="utf-8")

    cmd = [
        "codex", "exec",
        "--model", model_id,
        "--json",
        "--ephemeral",
        "--skip-git-repo-check",
        "-o", str(output_file),
    ]
    if tmp_schema:
        cmd.extend(["--output-schema", tmp_schema])
    cmd.extend(extra_args)
    cmd.append(combined_prompt)

    LOGGER.debug("codex invocation model=%s sidecar=%s", model_id, bool(sidecar_dir))
    return CodexInvocation(
        cmd=cmd,
        cwd=sidecar_dir or None,
        timeout=timeout,
        output_file=output_file,
        _tmp_schema=tmp_schema,
        _sidecar_dir=sidecar_dir,
    )


# ── Stage 2: Execute + persist to disk ─────────────────────────────────────

def _execute_codex(inv: CodexInvocation, run_dir: Path) -> CodexRawOutput:
    """Run subprocess; write stdout/stderr to disk before anything else."""
    started_at = datetime.now(timezone.utc)
    proc = subprocess.run(
        inv.cmd, capture_output=True, text=True,
        timeout=inv.timeout, cwd=inv.cwd,
    )
    finished_at = datetime.now(timezone.utc)

    # Persist to disk immediately — before error-checking or parsing.
    stdout_path = run_dir / "subprocess.stdout.codex.jsonl"
    stderr_path = run_dir / "subprocess.stderr.codex.txt"
    stdout_path.write_text(proc.stdout or "", encoding="utf-8")
    stderr_path.write_text(proc.stderr or "", encoding="utf-8")

    if proc.returncode != 0:
        raise RuntimeError(
            f"codex subprocess failed (exit {proc.returncode}): {proc.stderr[:400]}"
        )

    return CodexRawOutput(
        returncode=proc.returncode,
        stdout_path=stdout_path,
        stderr_path=stderr_path,
        output_file=inv.output_file,
        started_at=started_at,
        finished_at=finished_at,
    )


# ── Stage 3: Parse from disk ────────────────────────────────────────────────

def _parse_codex_output(raw: CodexRawOutput) -> CodexParsed:
    """Read the on-disk files and extract answer text, tokens, and traces."""
    stdout_text = raw.stdout_path.read_text(encoding="utf-8", errors="replace")

    # Primary answer: codex -o output file.
    raw_text = raw.output_file.read_text(encoding="utf-8").strip() if raw.output_file.exists() else ""
    if not raw_text:
        # Fallback: last non-JSON line in the stdout stream.
        lines = [ln.strip() for ln in stdout_text.splitlines() if ln.strip()]
        for line in reversed(lines):
            if not line.startswith("{"):
                raw_text = line
                break

    prompt_tokens, completion_tokens, cached_tokens, thinking_tokens = _extract_codex_tokens(stdout_text)
    tool_traces = _extract_codex_tool_traces(stdout_text)

    return CodexParsed(
        raw_text=raw_text,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        cached_tokens=cached_tokens,
        thinking_tokens=thinking_tokens,
        tool_traces=tool_traces,
    )


# ── Orchestrator ────────────────────────────────────────────────────────────

def call_codex(
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
        _tmp_run_dir = tempfile.mkdtemp(prefix="vsevals_codex_run_")
        rd = Path(_tmp_run_dir)

    combined_prompt = system_prompt + "\n\n" + user_prompt
    inv = _build_codex_invocation(
        model_id=model_id, combined_prompt=combined_prompt,
        cfg=cfg, tool_schemas=tool_schemas,
        sidecar_files=sidecar_files, timeout=timeout,
        run_dir=rd,
    )

    raw_stdout = raw_stderr = ""
    try:
        # Stage 2 → Stage 3: execute writes to disk, parse reads from disk.
        sub = _execute_codex(inv, rd)
        parsed = _parse_codex_output(sub)
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
        request_id=None,
        finish_reason="stop",
        tool_traces=parsed.tool_traces,
        subprocess_stdout=raw_stdout,
        subprocess_stderr=raw_stderr,
    )
