from __future__ import annotations

import json
import logging
import re
import shlex
import shutil
import subprocess
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from vsevals.models import RunConfig, TokenUsage, LLMResult, ToolTrace, compute_cost
from vsevals.harness_mcp import HarnessMCPServer
from . import _parse_payload, _int_or_none

LOGGER = logging.getLogger(__name__)


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
                # Normalise to the same mcp__<server>__<tool> convention used by
                # claudecode so runner.py voltsnip_tool_call_count is accurate.
                tool_name = f"mcp__{server}__{tool}"
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


def _extract_codex_stream_error(stdout: str) -> str | None:
    """Return a terminal stream error message when codex reports one.

    Codex can exit with returncode=0 while emitting error events in the
    JSONL stream.  Those runs must be treated as provider failures so they
    are not persisted as status=ok with empty or corrupted output.
    """
    for line in stdout.splitlines():
        line = line.strip()
        if not line or not line.startswith("{"):
            continue
        try:
            evt = json.loads(line)
        except Exception:
            continue
        if not isinstance(evt, dict):
            continue
        etype = evt.get("type", "")
        if etype == "error":
            msg = evt.get("message") or evt.get("error") or ""
            return str(msg) if msg else "codex stream returned error event"
        if etype in ("response.failed", "response.incomplete"):
            reason = evt.get("response", {}).get("status_details", {}).get("reason", "")
            msg = reason or evt.get("error") or ""
            return str(msg) if msg else f"codex stream: {etype}"
    return None


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
    repo_root: str | None = None,
) -> LLMResult:
    if not shutil.which("codex"):
        raise RuntimeError("codex binary not found on PATH — install the OpenAI Codex CLI")

    timeout = max(600, cfg.llm_timeout_seconds * 2) if tool_schemas else cfg.llm_timeout_seconds
    t0 = datetime.now(timezone.utc)
    perf0 = time.perf_counter()

    _tmp_run_dir = ""
    rd = Path(run_dir) if run_dir else Path(_tmp_run_dir := tempfile.mkdtemp(prefix="vsevals_codex_run_"))

    combined_prompt = system_prompt + "\n\n" + user_prompt

    _ = repo_root
    sidecar_dir = tempfile.mkdtemp(prefix="vsevals_codex_wd_")
    if sidecar_files:
        for filename, content in sidecar_files.items():
            codex_filename = ".agents/" + filename if filename.startswith("skills/") else filename
            dest = Path(sidecar_dir) / codex_filename
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text(content, encoding="utf-8")

    harness_server: HarnessMCPServer | None = None
    _APPROVAL_NEVER = ["-a", "never"]
    extra_args: list[str] = [*_APPROVAL_NEVER, "--sandbox", "read-only", "--disable", "unified_exec", "-c", "mcp_servers={}"]

    if tool_schemas:
        base_url = (cfg.voltsnip_base_url or "http://localhost:8000").rstrip("/")
        harness_server = HarnessMCPServer(Path(sidecar_dir), base_url, include_fs_tools=True).start()
        extra_args.extend(["-c", f"mcp_servers.voltsnip.url=http://127.0.0.1:{harness_server.port}/mcp"])

    if cfg.reasoning_effort:
        extra_args.extend(["-c", f"model_reasoning_effort={cfg.reasoning_effort}"])

    output_file = rd / "codex_last_message.txt"
    output_file.touch()

    tmp_schema = ""
    if cfg.structured_output:
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", prefix="vsevals_codex_schema_", delete=False) as sf:
            json.dump({"type": "object", "properties": {"code": {"type": "string"}, "comments": {"type": "string"}}, "required": ["code", "comments"], "additionalProperties": False}, sf)
            tmp_schema = sf.name

    cmd = ["codex"] + _APPROVAL_NEVER + [
        "exec", "--model", model_id, "--json", "--ephemeral",
        "--skip-git-repo-check", "--disable", "shell_tool", "-o", str(output_file),
    ]
    if tmp_schema:
        cmd.extend(["--output-schema", tmp_schema])
    cmd.extend(["-C", sidecar_dir])
    cmd.extend(a for a in extra_args if a not in _APPROVAL_NEVER)
    cmd.append(combined_prompt)

    LOGGER.debug("codex invocation model=%s sidecar=%s harness_mcp_port=%s",
                 model_id, bool(sidecar_files), harness_server.port if harness_server else None)

    raw_stdout = raw_stderr = ""
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, cwd=sidecar_dir)

        stdout_path = rd / "subprocess.stdout.codex.jsonl"
        stderr_path = rd / "subprocess.stderr.codex.txt"
        stdout_path.write_text(proc.stdout or "", encoding="utf-8")
        stderr_path.write_text(proc.stderr or "", encoding="utf-8")

        cmd_path = rd / "subprocess.cmd.codex.sh"
        cmd_path.write_text(
            "#!/usr/bin/env bash\n# Auto-generated — reproduces the exact codex subprocess invocation.\n"
            f"cd {shlex.quote(sidecar_dir)}\nexec " + shlex.join(cmd) + "\n",
            encoding="utf-8",
        )
        cmd_path.chmod(0o755)

        if proc.returncode != 0:
            raise RuntimeError(f"codex subprocess failed (exit {proc.returncode}): {proc.stderr[:400]}")

        stream_err = _extract_codex_stream_error(proc.stdout or "")
        if stream_err:
            raise RuntimeError(f"codex stream error: {stream_err}")

        raw_stdout = stdout_path.read_text(encoding="utf-8", errors="replace")
        raw_stderr = stderr_path.read_text(encoding="utf-8", errors="replace")

    finally:
        if harness_server is not None:
            try:
                harness_server.stop()
            except Exception:
                pass
        if tmp_schema:
            try:
                Path(tmp_schema).unlink(missing_ok=True)
            except Exception:
                pass
        shutil.rmtree(sidecar_dir, ignore_errors=True)
        if _tmp_run_dir:
            shutil.rmtree(_tmp_run_dir, ignore_errors=True)

    raw_text = output_file.read_text(encoding="utf-8").strip() if output_file.exists() else ""
    if not raw_text:
        for line in reversed([ln.strip() for ln in raw_stdout.splitlines() if ln.strip()]):
            if not line.startswith("{"):
                raw_text = line
                break

    pt, ct, cached, thinking = _extract_codex_tokens(raw_stdout)
    tool_traces = _extract_codex_tool_traces(raw_stdout)

    result_parsed, fallback = _parse_payload(raw_text, cfg.structured_output)

    # Fragment injection guard: prepend def header if codex omitted it.
    _code = result_parsed.get("code", "") if isinstance(result_parsed, dict) else ""
    _stripped = _code.strip()
    if _stripped and not _stripped.splitlines()[0].lstrip().startswith(("def ", "class ", "async def ")):
        _sig_match = re.search(r'^((?:async\s+)?def\s+\w+[^:]+:|class\s+\w+[^:]+:)', combined_prompt, re.MULTILINE)
        if _sig_match:
            _sig = _sig_match.group(1)
            LOGGER.warning("codex fragment injection detected — prepending signature: %r", _sig)
            result_parsed = dict(result_parsed)
            result_parsed["code"] = _sig + "\n" + _stripped

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
        request_id=None,
        finish_reason="stop",
        tool_traces=tool_traces,
        subprocess_stdout=raw_stdout,
        subprocess_stderr=raw_stderr,
    )
