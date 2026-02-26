"""LLM dispatch layer — four providers, zero LangChain.

Providers
---------
openai      → OpenAI SDK (gpt-*)
              P0–P3 (no tools): Chat Completions API.
              P4–P6a (tool variants): Responses API + native MCP connection to
              {voltsnip_base_url}/mcp — OpenAI handles the tool loop server-side.
              Requires a publicly accessible backend URL (not localhost).
anthropic   → Anthropic SDK (claude-*, includes native SDK tool-calling loop)
claudecode  → `claude -p` subprocess (Claude Code stored auth; no API key needed)
              P4–P6a: writes temp --mcp-config JSON pointing at VoltSnip MCP HTTP
              endpoint. Works with localhost. Cannot run inside a claude session.
codex       → `codex exec` subprocess (Codex CLI stored auth; no API key needed)
              P4–P6a: injects MCP server per-run via -c mcp_servers.voltsnip.*
              Works with localhost. Run from a plain terminal.
mock        → echo stub for unit tests

Tool-calling paths
------------------
openai (P4–P6a):     Responses API remote MCP — needs public backend URL.
anthropic (P4–P6a):  native SDK tool loop (up to max_tool_turns iterations).
claudecode (P4–P6a): --mcp-config → localhost MCP works.
codex (P4–P6a):      -c mcp_servers.voltsnip.url=... → localhost MCP works.

Entry point
-----------
    result = call_llm(
        model_name="codex:gpt-5.3-codex",
        system_prompt=...,
        user_prompt=...,
        cfg=RunConfig(...),
        provider_keys={},
        tool_schemas=[...],      # optional — enables tool loop
        tool_handlers={...},     # optional — used by anthropic only
        max_tool_turns=8,        # optional
    )
"""

from __future__ import annotations

import json
import logging
import os
import re
import subprocess
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from vsevals.models import GeneratedPayload, RunConfig, TokenUsage, ToolTrace

LOGGER = logging.getLogger(__name__)

# Regex to find voltsnip snippet keys in raw text
_KEY_RE = re.compile(r"\bvoltsnip/[a-z0-9][a-z0-9_./-]*", re.IGNORECASE)


# ---------------------------------------------------------------------------
# Per-model pricing table (USD per 1 million tokens)
# ---------------------------------------------------------------------------
# Format: model_id (the part after the "provider:" colon) → (input_$/M, output_$/M)
# Update as pricing changes.  Missing models return cost_usd=None.
# Pricing as of early 2026 — update to official rates as they are published.
_PRICING: dict[str, tuple[float, float]] = {
    # ── OpenAI ────────────────────────────────────────────────────────────
    "gpt-5.2":          (15.00,  60.00),   # flagship
    "gpt-5":            (15.00,  60.00),
    "gpt-5.3-codex":    (15.00,  60.00),
    "gpt-5.2-codex":    (15.00,  60.00),
    "gpt-5.1-codex":    (15.00,  60.00),
    "gpt-5-mini":       ( 0.40,   1.60),
    "gpt-5-nano":       ( 0.10,   0.40),
    "gpt-4o":           ( 2.50,  10.00),
    "gpt-4o-mini":      ( 0.15,   0.60),
    "o3":               (10.00,  40.00),
    "o3-mini":          ( 1.10,   4.40),
    "o1":               (15.00,  60.00),
    "o1-mini":          ( 3.00,  12.00),
    # ── Anthropic ─────────────────────────────────────────────────────────
    "claude-opus-4-6":  (15.00,  75.00),   # flagship Claude
    "claude-opus-4-5":  (15.00,  75.00),
    "claude-sonnet-4-6": (3.00,  15.00),
    "claude-sonnet-4-5": (3.00,  15.00),
    "claude-haiku-4-5": ( 0.80,   4.00),
    "claude-haiku-4-4": ( 0.25,   1.25),
}


def _compute_cost(model_id: str, prompt_tokens: int, completion_tokens: int) -> float | None:
    """Return estimated cost in USD, or None if model_id not in pricing table."""
    pricing = _PRICING.get(model_id)
    if pricing is None:
        return None
    in_rate, out_rate = pricing
    return round(
        (prompt_tokens * in_rate + completion_tokens * out_rate) / 1_000_000,
        8,
    )


# ---------------------------------------------------------------------------
# Public result type
# ---------------------------------------------------------------------------


class LLMResult:
    """Returned by call_llm()."""

    __slots__ = (
        "raw_output",
        "parsed_output",
        "token_usage",
        "structured_output_attempted",
        "structured_output_succeeded",
        "fallback_parser_used",
        "request_started_at",
        "request_finished_at",
        "request_latency_ms",
        "request_id",
        "finish_reason",
        "tool_traces",   # populated by claudecode/codex MCP paths
    )

    def __init__(
        self,
        *,
        raw_output: str,
        parsed_output: GeneratedPayload,
        token_usage: TokenUsage,
        structured_output_attempted: bool,
        structured_output_succeeded: bool,
        fallback_parser_used: bool,
        request_started_at: datetime | None,
        request_finished_at: datetime | None,
        request_latency_ms: int | None,
        request_id: str | None,
        finish_reason: str | None,
        tool_traces: list[ToolTrace] | None = None,
    ) -> None:
        self.raw_output = raw_output
        self.parsed_output = parsed_output
        self.token_usage = token_usage
        self.structured_output_attempted = structured_output_attempted
        self.structured_output_succeeded = structured_output_succeeded
        self.fallback_parser_used = fallback_parser_used
        self.request_started_at = request_started_at
        self.request_finished_at = request_finished_at
        self.request_latency_ms = request_latency_ms
        self.request_id = request_id
        self.finish_reason = finish_reason
        self.tool_traces: list[ToolTrace] = tool_traces or []


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def call_llm(
    *,
    model_name: str,
    system_prompt: str,
    user_prompt: str,
    cfg: RunConfig,
    provider_keys: dict[str, str],
    tool_schemas: list[dict[str, Any]] | None = None,
    tool_handlers: dict[str, Any] | None = None,
    max_tool_turns: int = 8,
    sidecar_files: dict[str, str] | None = None,
) -> LLMResult:
    """Dispatch an LLM call to the right provider.

    `sidecar_files` are only used by subprocess providers (`claudecode`, `codex`).
    """
    provider, model_id = _parse_model(model_name)

    if provider == "mock":
        return _call_mock(system_prompt, user_prompt, cfg)

    if provider == "claudecode":
        result = _call_claudecode(
            model_id=model_id,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            cfg=cfg,
            tool_schemas=tool_schemas,
            max_tool_turns=max_tool_turns,
            sidecar_files=sidecar_files,
        )
    elif provider == "codex":
        result = _call_codex(
            model_id=model_id,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            cfg=cfg,
            tool_schemas=tool_schemas,
            max_tool_turns=max_tool_turns,
            sidecar_files=sidecar_files,
        )
    elif provider == "openai":
        api_key = _resolve_key(provider, cfg, provider_keys)
        result = _call_openai(
            model_id=model_id,
            api_key=api_key,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            cfg=cfg,
            tool_schemas=tool_schemas,
            tool_handlers=tool_handlers,
            max_tool_turns=max_tool_turns,
        )
    elif provider == "anthropic":
        api_key = _resolve_key(provider, cfg, provider_keys)
        result = _call_anthropic(
            model_id=model_id,
            api_key=api_key,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            cfg=cfg,
            tool_schemas=tool_schemas,
            tool_handlers=tool_handlers,
            max_tool_turns=max_tool_turns,
        )
    else:
        raise ValueError(f"unsupported provider '{provider}' in model '{model_name}'")

    return result


# ---------------------------------------------------------------------------
# Judge call (single-shot, no tools, returns raw text)
# ---------------------------------------------------------------------------


def call_judge(
    *,
    model_name: str,
    system_prompt: str,
    user_prompt: str,
    cfg: RunConfig,
    provider_keys: dict[str, str],
) -> str | None:
    """Call a judge model; return raw text output or None on failure."""
    provider, model_id = _parse_model(model_name)

    try:
        raw: str | None = None
        if provider == "claudecode":
            result = _call_claudecode(model_id=model_id, system_prompt=system_prompt, user_prompt=user_prompt, cfg=cfg)
            raw = result.raw_output or None
        else:
            api_key = _resolve_key(provider, cfg, provider_keys)
            if provider == "openai":
                result = _call_openai(model_id=model_id, api_key=api_key, system_prompt=system_prompt, user_prompt=user_prompt, cfg=cfg)
                raw = result.raw_output or None
            elif provider == "anthropic":
                result = _call_anthropic(model_id=model_id, api_key=api_key, system_prompt=system_prompt, user_prompt=user_prompt, cfg=cfg)
                raw = result.raw_output or None
        return raw
    except Exception as exc:
        LOGGER.debug("judge call failed model=%s error=%s", model_name, exc)
    return None


# ---------------------------------------------------------------------------
# Provider implementations
# ---------------------------------------------------------------------------


def _call_mock(system_prompt: str, user_prompt: str, cfg: RunConfig) -> LLMResult:
    """Echo stub — returns empty code payload. Used with provider=mock."""
    now = datetime.now(timezone.utc)
    raw = '{"code": "", "comments": "mock echo"}'
    parsed, fallback = _parse_payload(raw, cfg.structured_output)
    return LLMResult(
        raw_output=raw, parsed_output=parsed,
        token_usage=TokenUsage(prompt_tokens=0, completion_tokens=0, total_tokens=0),
        structured_output_attempted=cfg.structured_output, structured_output_succeeded=not fallback,
        fallback_parser_used=fallback, request_started_at=now, request_finished_at=now,
        request_latency_ms=0, request_id=None, finish_reason="stop",
    )


def _claudecode_error(stdout: str, stderr: str, prefix: str) -> RuntimeError:
    """Build a descriptive RuntimeError from a failed `claude -p` subprocess.

    claude writes errors to stdout (not stderr) — sometimes as plain text,
    sometimes as a JSON result object with is_error=true.
    We try JSON first, then fall back to raw text, and detect common causes.
    """
    combined = ((stdout or "") + "\n" + (stderr or "")).strip()

    # Try to parse JSON and extract the result message
    result_msg = ""
    try:
        data = json.loads(stdout or "")
        if isinstance(data, dict):
            result_msg = data.get("result") or ""
    except Exception:
        pass

    detail = (result_msg or combined)[:500]

    # Classify common failure patterns
    lc = detail.lower()
    if "nested" in lc or "another claude code" in lc or "claudecode" in detail:
        return RuntimeError(
            "claudecode blocked: cannot run inside an active Claude Code session. "
            "Open a plain terminal (outside Claude Code) and re-run from there."
        )
    if "external api key" in lc or ("invalid api key" in lc and "external" in lc):
        return RuntimeError(
            f"claudecode API key conflict: {result_msg or detail}. "
            "This should be fixed automatically — if you see this error, "
            "ensure ANTHROPIC_API_KEY is NOT exported in the shell running the script "
            "(it should only be in .env, read by the shell script, not re-exported)."
        )
    if "invalid api key" in lc or "authentication" in lc or "unauthorized" in lc:
        return RuntimeError(
            f"claudecode auth error: {result_msg or detail}. "
            "Run `claude` in a terminal to check your Claude Code login status."
        )
    return RuntimeError(f"{prefix} (exit 1): {detail}")


def _claudecode_env() -> dict[str, str]:
    """Return a subprocess env for `claude -p` with Anthropic API keys stripped.

    When ANTHROPIC_API_KEY (or ANTHROPIC_BASE_URL) is present in the current
    environment, the Claude Code CLI treats it as an "external API key" and
    tries to use it directly — overriding any stored OAuth / subscription auth.
    If that key is invalid the CLI returns exit 1 with "Fix external API key".

    The claudecode provider is designed to use Claude Code's stored credentials
    (OAuth login or ~/.claude stored key), so we simply remove these env vars
    before launching the subprocess.
    """
    return {
        k: v for k, v in os.environ.items()
        if k not in ("ANTHROPIC_API_KEY", "ANTHROPIC_BASE_URL", "ANTHROPIC_AUTH_TOKEN")
    }


def _make_sidecar_dir(sidecar_files: dict[str, str]) -> str:
    """Create a temp directory and write sidecar files (CLAUDE.md, AGENTS.md, SKILL.md, …) into it.

    Returns the directory path. Caller is responsible for shutil.rmtree() cleanup.
    These files are auto-loaded by the CLI tools:
      - claude: reads CLAUDE.md from cwd as project context; SKILL.md for skill definitions.
      - codex:  reads AGENTS.md from cwd as agent instructions.
    """
    import shutil
    tmpdir = tempfile.mkdtemp(prefix="vsevals_sidecar_")
    try:
        for filename, content in sidecar_files.items():
            Path(tmpdir, filename).write_text(content, encoding="utf-8")
    except Exception:
        shutil.rmtree(tmpdir, ignore_errors=True)
        raise
    return tmpdir


def _make_isolated_cli_cwd(sidecar_files: dict[str, str] | None) -> str:
    """Create a fresh per-call cwd for CLI providers.

    This isolates each run from prior local project context/session artifacts.
    If sidecar files are provided (CLAUDE.md / AGENTS.md / SKILL.md), they are
    written into this isolated directory; otherwise the directory is empty.
    """
    return _make_sidecar_dir(sidecar_files or {})


def _call_claudecode(
    *,
    model_id: str,
    system_prompt: str,
    user_prompt: str,
    cfg: RunConfig,
    tool_schemas: list[dict[str, Any]] | None = None,
    max_tool_turns: int = 8,
    sidecar_files: dict[str, str] | None = None,
) -> LLMResult:
    """Call via `claude -p` subprocess (no ANTHROPIC_API_KEY required).

    Two paths:
    - No tool_schemas: single-shot (--max-turns 1).
    - tool_schemas provided: uses live VoltSnip MCP HTTP endpoint + stream-json output.

    sidecar_files: optional dict of filename→content to write into a temp cwd so that
    claude auto-loads CLAUDE.md (project context) and SKILL.md (skills).
    """
    if tool_schemas:
        return _call_claudecode_with_mcp(
            model_id=model_id,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            cfg=cfg,
            max_tool_turns=max_tool_turns,
            sidecar_files=sidecar_files,
        )
    return _call_claudecode_single_shot(
        model_id=model_id,
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        cfg=cfg,
        sidecar_files=sidecar_files,
    )


def _call_claudecode_single_shot(
    *, model_id: str, system_prompt: str, user_prompt: str, cfg: RunConfig,
    sidecar_files: dict[str, str] | None = None,
) -> LLMResult:
    """Single-shot `claude -p` — no tools, --max-turns 1.

    Uses --output-format stream-json (JSONL) for all models so that extended-
    thinking models (e.g. claude-opus-4-6) are handled correctly.  The older
    --output-format json mode returns result="" for opus because the answer
    lives in thinking/content blocks rather than the flat "result" field;
    stream-json surfaces every content block and _parse_claudecode_stream_json
    extracts text from them reliably.

    If sidecar_files provided, writes them (CLAUDE.md, SKILL.md, …) into a temp
    directory used as the subprocess cwd so claude auto-loads them as project context.
    """
    import shutil
    t0 = datetime.now(timezone.utc)
    perf0 = time.perf_counter()

    sidecar_dir: str | None = None
    try:
        sidecar_dir = _make_isolated_cli_cwd(sidecar_files)
        if sidecar_files:
            LOGGER.debug("claudecode sidecar dir=%s files=%s", sidecar_dir, list(sidecar_files))
        else:
            LOGGER.debug("claudecode isolated cwd=%s (no sidecars)", sidecar_dir)

        cmd = [
            "claude", "-p", user_prompt,
            "--output-format", "stream-json",   # JSONL; handles extended-thinking models
            "--verbose",                         # required with stream-json + -p
            "--model", model_id,
            "--system-prompt", system_prompt,
            "--max-turns", "1",
            "--no-session-persistence",
            # Disallow filesystem/web tools for single-shot (P0–P3) runs.
            # Without this, thorough models (e.g. opus) try to read the actual
            # target source file from the eval working directory, fail with tool
            # errors, and produce empty output.  These variants are designed to
            # work from injected prompt context only — no file access is needed.
            "--disallowed-tools", "Bash,Read,Write,Edit,Glob,NotebookEdit,WebSearch,WebFetch",
        ]
        LOGGER.debug("claudecode single-shot model=%s sidecar=%s timeout=%ds",
                     model_id, bool(sidecar_dir), cfg.llm_timeout_seconds)
        proc = subprocess.run(
            cmd, capture_output=True, text=True, timeout=cfg.llm_timeout_seconds,
            cwd=sidecar_dir,
            env=_claudecode_env(),  # strip ANTHROPIC_API_KEY so stored auth is used
        )
        if proc.returncode != 0:
            raise _claudecode_error(proc.stdout, proc.stderr, "claude subprocess failed")

        raw, input_tok, output_tok, thinking_tok, session_id, tool_traces = _parse_claudecode_stream_json(proc.stdout)
        parsed, fallback = _parse_payload(raw, cfg.structured_output)

        return LLMResult(
            raw_output=raw, parsed_output=parsed,
            token_usage=TokenUsage(
                prompt_tokens=input_tok, completion_tokens=output_tok,
                total_tokens=input_tok + output_tok,
                thinking_tokens=thinking_tok,
                cost_usd=_compute_cost(model_id, input_tok, output_tok),
            ),
            structured_output_attempted=cfg.structured_output,
            structured_output_succeeded=not fallback if cfg.structured_output else False,
            fallback_parser_used=fallback,
            request_started_at=t0, request_finished_at=datetime.now(timezone.utc),
            request_latency_ms=int((time.perf_counter() - perf0) * 1000),
            request_id=session_id, finish_reason="stop",
            tool_traces=tool_traces,
        )
    finally:
        if sidecar_dir:
            shutil.rmtree(sidecar_dir, ignore_errors=True)


def _call_claudecode_with_mcp(
    *,
    model_id: str,
    system_prompt: str,
    user_prompt: str,
    cfg: RunConfig,
    max_tool_turns: int = 8,
    sidecar_files: dict[str, str] | None = None,
) -> LLMResult:
    """Tool-calling `claude -p` using the live VoltSnip MCP HTTP endpoint.

    Uses --output-format stream-json (JSONL) so every tool_use call and
    tool_result response appears inline in stdout — this gives us full
    tool_traces without any server-side logging or proxy needed.

    If sidecar_files provided, writes CLAUDE.md / SKILL.md into a temp cwd so
    claude auto-loads them as project context on top of --system-prompt.
    """
    import shutil
    t0 = datetime.now(timezone.utc)
    perf0 = time.perf_counter()

    base_url = (cfg.voltsnip_base_url or "http://localhost:8001").rstrip("/")
    # Use trailing slash to avoid FastAPI 307 redirect /mcp -> /mcp/.
    mcp_url = f"{base_url}/mcp/"

    mcp_config = {
        "mcpServers": {
            "voltsnip": {
                "type": "http",
                "url": mcp_url,
            }
        }
    }

    sidecar_dir: str | None = None
    tmp_cfg_path: str | None = None
    try:
        sidecar_dir = _make_isolated_cli_cwd(sidecar_files)
        if sidecar_files:
            LOGGER.debug("claudecode-mcp sidecar dir=%s files=%s", sidecar_dir, list(sidecar_files))
        else:
            LOGGER.debug("claudecode-mcp isolated cwd=%s (no sidecars)", sidecar_dir)

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", prefix="vsevals_mcp_", delete=False
        ) as fh:
            json.dump(mcp_config, fh)
            tmp_cfg_path = fh.name

        cmd = [
            "claude", "-p", user_prompt,
            "--output-format", "stream-json",   # JSONL: gives us tool_use events
            "--verbose",                        # required by claude when using stream-json with -p
            "--model", model_id,
            "--system-prompt", system_prompt,
            "--mcp-config", tmp_cfg_path,
            "--strict-mcp-config",
            "--no-session-persistence",
            "--max-turns", str(max(1, max_tool_turns)),
        ]
        mcp_timeout = max(600, cfg.llm_timeout_seconds * 2)
        LOGGER.debug("claudecode mcp-tool-loop model=%s mcp_cfg=%s sidecar=%s timeout=%ds",
                     model_id, tmp_cfg_path, bool(sidecar_dir), mcp_timeout)
        proc = subprocess.run(
            cmd, capture_output=True, text=True, timeout=mcp_timeout,
            cwd=sidecar_dir,
            env=_claudecode_env(),  # strip ANTHROPIC_API_KEY so stored auth is used
        )
        if proc.returncode != 0:
            raise _claudecode_error(proc.stdout, proc.stderr, "claude subprocess (mcp) failed")
    finally:
        if tmp_cfg_path:
            try:
                Path(tmp_cfg_path).unlink(missing_ok=True)
            except Exception:
                pass
        if sidecar_dir:
            shutil.rmtree(sidecar_dir, ignore_errors=True)

    raw, input_tok, output_tok, thinking_tok, session_id, tool_traces = _parse_claudecode_stream_json(proc.stdout)
    parsed, fallback = _parse_payload(raw, cfg.structured_output)

    return LLMResult(
        raw_output=raw, parsed_output=parsed,
        token_usage=TokenUsage(
            prompt_tokens=input_tok, completion_tokens=output_tok,
            total_tokens=input_tok + output_tok,
            thinking_tokens=thinking_tok,
            cost_usd=_compute_cost(model_id, input_tok, output_tok),
        ),
        structured_output_attempted=cfg.structured_output,
        structured_output_succeeded=not fallback if cfg.structured_output else False,
        fallback_parser_used=fallback,
        request_started_at=t0, request_finished_at=datetime.now(timezone.utc),
        request_latency_ms=int((time.perf_counter() - perf0) * 1000),
        request_id=session_id, finish_reason="stop",
        tool_traces=tool_traces,
    )


def _parse_claudecode_stream_json(
    stdout: str,
) -> tuple[str, int, int, int | None, str | None, list[ToolTrace]]:
    """Parse claude --output-format stream-json JSONL output.

    Returns (raw_output, prompt_tokens, completion_tokens, thinking_tokens, session_id, tool_traces).

    The stream-json format emits one JSON object per line:
      {"type":"assistant","message":{"content":[{"type":"tool_use","id":"...","name":"...","input":{}}]}}
      {"type":"tool","tool_use_id":"...","content":"..."}   (MCP tool result)
      {"type":"result","result":"...","session_id":"...","usage":{...}}
    """
    raw = ""
    input_tok = 0
    output_tok = 0
    thinking_tok: int | None = None
    session_id: str | None = None
    tool_traces: list[ToolTrace] = []

    # Track open tool calls by id to pair with results
    pending: dict[str, dict] = {}  # tool_use_id → {name, input, started_at, t0}

    for line in stdout.splitlines():
        line = line.strip()
        if not line or not line.startswith("{"):
            continue
        try:
            obj = json.loads(line)
        except Exception:
            continue
        if not isinstance(obj, dict):
            continue

        evt_type = obj.get("type", "")

        # Final result event — extract text, usage, session_id
        if evt_type == "result":
            raw = obj.get("result") or ""
            session_id = obj.get("session_id")
            usage = obj.get("usage") or {}
            input_tok = int(usage.get("input_tokens", 0) or 0)
            output_tok = int(usage.get("output_tokens", 0) or 0)
            # thinking / reasoning tokens (extended thinking or future model variants)
            thinking_tok = _int_or_none(
                usage.get("thinking_tokens")
                or usage.get("reasoning_tokens")
            )
            continue

        # Assistant message — scan content blocks for tool_use
        if evt_type == "assistant":
            msg = obj.get("message") or {}
            content = msg.get("content") or []
            if isinstance(content, str):
                # Plain text content — candidate for raw if result not found
                if not raw:
                    raw = content
                continue
            for block in (content if isinstance(content, list) else []):
                if not isinstance(block, dict):
                    continue
                if block.get("type") == "tool_use":
                    tid = block.get("id", "")
                    pending[tid] = {
                        "name": block.get("name", ""),
                        "input": block.get("input") or {},
                        "started_at": datetime.now(timezone.utc),
                        "t0": time.perf_counter(),
                    }
                elif block.get("type") == "text" and not raw:
                    raw = raw or (block.get("text") or "")
            continue

        # Tool result — pair with pending call by id
        if evt_type in ("tool", "tool_result"):
            tid = obj.get("tool_use_id", "") or obj.get("id", "")
            pending_call = pending.pop(tid, None)
            result_content = obj.get("content") or obj.get("output") or ""
            if isinstance(result_content, list):
                result_content = json.dumps(result_content, ensure_ascii=False)

            started_at = (pending_call or {}).get("started_at", datetime.now(timezone.utc))
            t0_call = (pending_call or {}).get("t0", time.perf_counter())
            duration_ms = int((time.perf_counter() - t0_call) * 1000)
            tool_name = (pending_call or {}).get("name", "")
            tool_args = (pending_call or {}).get("input", {})

            # Parse result for snippet count
            try:
                result_obj = json.loads(result_content) if isinstance(result_content, str) else result_content
            except Exception:
                result_obj = None
            snippet_count = len(result_obj) if isinstance(result_obj, list) else None

            tool_traces.append(ToolTrace(
                roundtrip=len(tool_traces) + 1,
                tool_name=tool_name,
                tool_args=tool_args,
                tool_result={"retrieved": snippet_count} if snippet_count is not None else {"raw": str(result_content)[:200]},
                error=None,
                started_at=started_at,
                finished_at=datetime.now(timezone.utc),
                duration_ms=duration_ms,
            ))
            continue

    # Flush any tool calls with no matching result (shouldn't happen, but be safe)
    for tid, call in pending.items():
        tool_traces.append(ToolTrace(
            roundtrip=len(tool_traces) + 1,
            tool_name=call.get("name", ""),
            tool_args=call.get("input", {}),
            tool_result=None,
            error="no tool result received",
            started_at=call.get("started_at", datetime.now(timezone.utc)),
            finished_at=datetime.now(timezone.utc),
            duration_ms=0,
        ))

    return raw, input_tok, output_tok, thinking_tok, session_id, tool_traces


# ---------------------------------------------------------------------------
# Codex CLI provider
# ---------------------------------------------------------------------------


def _call_codex(
    *,
    model_id: str,
    system_prompt: str,
    user_prompt: str,
    cfg: RunConfig,
    tool_schemas: list[dict[str, Any]] | None = None,
    max_tool_turns: int = 8,
    sidecar_files: dict[str, str] | None = None,
) -> LLMResult:
    """Route to codex MCP (tools) or single-shot based on tool_schemas.

    sidecar_files: optional AGENTS.md / SKILL.md written to a temp cwd so
    codex auto-loads them as agent instructions (AGENTS.md is read by codex on startup).
    """
    if tool_schemas:
        return _call_codex_with_mcp(
            model_id=model_id,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            cfg=cfg,
            max_tool_turns=max_tool_turns,
            sidecar_files=sidecar_files,
        )
    return _call_codex_single_shot(
        model_id=model_id,
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        cfg=cfg,
        sidecar_files=sidecar_files,
    )


def _call_codex_single_shot(
    *,
    model_id: str,
    system_prompt: str,
    user_prompt: str,
    cfg: RunConfig,
    sidecar_files: dict[str, str] | None = None,
) -> LLMResult:
    """Single-shot `codex exec` — no tools."""
    return _run_codex_subprocess(
        model_id=model_id,
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        cfg=cfg,
        extra_args=[],
        timeout=cfg.llm_timeout_seconds,
        sidecar_files=sidecar_files,
    )


def _call_codex_with_mcp(
    *,
    model_id: str,
    system_prompt: str,
    user_prompt: str,
    cfg: RunConfig,
    max_tool_turns: int = 8,
    sidecar_files: dict[str, str] | None = None,
) -> LLMResult:
    """Tool-calling `codex exec` using the live VoltSnip MCP HTTP endpoint.

    Injects the VoltSnip MCP server per-run via -c flags so the Codex CLI can
    connect to the local backend at {voltsnip_base_url}/mcp without modifying
    ~/.codex/config.toml permanently. Codex handles the tool loop natively.
    """
    base_url = (cfg.voltsnip_base_url or "http://localhost:8001").rstrip("/")
    # Use trailing slash to avoid FastAPI 307 redirect /mcp -> /mcp/.
    mcp_url = f"{base_url}/mcp/"
    mcp_timeout = max(600, cfg.llm_timeout_seconds * 2)
    LOGGER.debug("codex mcp-tool-loop model=%s mcp_url=%s timeout=%ds", model_id, mcp_url, mcp_timeout)
    return _run_codex_subprocess(
        model_id=model_id,
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        cfg=cfg,
        extra_args=[
            "-c", "mcp_servers={}",
            "-c", f'mcp_servers.voltsnip.url="{mcp_url}"',
            "-c", "mcp_servers.voltsnip.enabled=true",
        ],
        timeout=mcp_timeout,
        sidecar_files=sidecar_files,
    )


def _run_codex_subprocess(
    *,
    model_id: str,
    system_prompt: str,
    user_prompt: str,
    cfg: RunConfig,
    extra_args: list[str],
    timeout: int,
    sidecar_files: dict[str, str] | None = None,
) -> LLMResult:
    """Core codex exec runner. Merges system+user prompt (no --system-prompt flag).

    If sidecar_files provided, writes them (AGENTS.md, SKILL.md, …) into a temp
    directory used as the subprocess cwd so codex auto-loads AGENTS.md as agent
    instructions on startup.  The combined_prompt still includes the full content
    (additive — ensures compatibility even if auto-loading is not active).
    """
    import shutil
    t0 = datetime.now(timezone.utc)
    perf0 = time.perf_counter()

    # Merge system+user: codex exec has no --system-prompt flag
    combined_prompt = f"{system_prompt}\n\n---\n\n{user_prompt}"

    sidecar_dir: str | None = None
    tmp_output: str | None = None
    try:
        sidecar_dir = _make_isolated_cli_cwd(sidecar_files)
        if sidecar_files:
            LOGGER.debug("codex sidecar dir=%s files=%s", sidecar_dir, list(sidecar_files))
        else:
            LOGGER.debug("codex isolated cwd=%s (no sidecars)", sidecar_dir)

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".txt", prefix="vsevals_codex_out_", delete=False
        ) as fh:
            tmp_output = fh.name

        cmd = [
            "codex", "exec",
            "--model", model_id,
            "--json",
            "--ephemeral",
            "--skip-git-repo-check",
            "-o", tmp_output,
            *extra_args,
            combined_prompt,
        ]
        LOGGER.debug("codex cmd model=%s sidecar=%s", model_id, bool(sidecar_dir))
        proc = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout,
            cwd=sidecar_dir,
        )
        if proc.returncode != 0:
            raise RuntimeError(
                f"codex subprocess failed (exit {proc.returncode}): {proc.stderr[:400]}"
            )

        # Final answer from -o file
        raw = Path(tmp_output).read_text(encoding="utf-8").strip() if Path(tmp_output).exists() else ""
        if not raw:
            # Fallback: last non-empty line of stdout (non-JSONL output)
            lines = [ln.strip() for ln in proc.stdout.splitlines() if ln.strip()]
            for line in reversed(lines):
                if not line.startswith("{"):
                    raw = line
                    break

        # Token usage + tool traces from JSONL event stream
        prompt_tokens, completion_tokens, thinking_tokens = _extract_codex_tokens(proc.stdout)
        tool_traces = _extract_codex_tool_traces(proc.stdout)

    finally:
        if tmp_output:
            try:
                Path(tmp_output).unlink(missing_ok=True)
            except Exception:
                pass
        if sidecar_dir:
            shutil.rmtree(sidecar_dir, ignore_errors=True)

    parsed, fallback = _parse_payload(raw, cfg.structured_output)
    return LLMResult(
        raw_output=raw, parsed_output=parsed,
        token_usage=TokenUsage(
            prompt_tokens=prompt_tokens, completion_tokens=completion_tokens,
            total_tokens=prompt_tokens + completion_tokens,
            thinking_tokens=thinking_tokens,
            cost_usd=_compute_cost(model_id, prompt_tokens, completion_tokens),
        ),
        structured_output_attempted=cfg.structured_output,
        structured_output_succeeded=not fallback if cfg.structured_output else False,
        fallback_parser_used=fallback,
        request_started_at=t0, request_finished_at=datetime.now(timezone.utc),
        request_latency_ms=int((time.perf_counter() - perf0) * 1000),
        request_id=None, finish_reason="stop",
        tool_traces=tool_traces,
    )


def _extract_codex_tokens(jsonl_text: str) -> tuple[int, int, int | None]:
    """Parse JSONL event stream from codex exec --json for token usage.

    Codex emits events as JSONL. We scan all lines defensively for any dict
    containing input_tokens / output_tokens (or prompt_tokens / completion_tokens).
    Returns (prompt_tokens, completion_tokens, thinking_tokens), defaulting to 0/None if not found.
    """
    prompt_tokens = 0
    completion_tokens = 0
    thinking_tokens: int | None = None
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
        usage = obj.get("usage") or {}
        # Try various key names used by different codex / OpenAI SDK versions
        pt = (
            obj.get("input_tokens")
            or obj.get("prompt_tokens")
            or usage.get("input_tokens")
            or usage.get("prompt_tokens")
            or 0
        )
        ct = (
            obj.get("output_tokens")
            or obj.get("completion_tokens")
            or usage.get("output_tokens")
            or usage.get("completion_tokens")
            or 0
        )
        if pt or ct:
            prompt_tokens = int(pt or 0)
            completion_tokens = int(ct or 0)
            # Reasoning / thinking tokens (o-series and future reasoning models)
            ct_details = (
                obj.get("completion_tokens_details")
                or usage.get("completion_tokens_details")
                or {}
            )
            thinking_tokens = _int_or_none(
                ct_details.get("reasoning_tokens")
                or obj.get("thinking_tokens")
                or obj.get("reasoning_tokens")
                or usage.get("thinking_tokens")
                or usage.get("reasoning_tokens")
            )
            break  # Take first usage event found
    return prompt_tokens, completion_tokens, thinking_tokens


def _extract_codex_tool_traces(jsonl_text: str) -> list[ToolTrace]:
    """Parse codex exec --json JSONL event stream for tool call traces.

    Codex emits OpenAI-style events. Tool calls appear as:
      {"type":"function_call","call_id":"...","name":"...","arguments":"..."}
      {"type":"function_call_output","call_id":"...","output":"..."}
    Or in newer codex versions:
      {"type":"response.output_item.added","item":{"type":"function_call","call_id":"...","name":"...","arguments":"..."}}
      {"type":"response.output_item.added","item":{"type":"function_call_output","call_id":"...","output":"..."}}
    Parsed defensively — unknown formats produce an empty list.
    """
    traces: list[ToolTrace] = []
    pending: dict[str, dict] = {}  # call_id → {name, args, started_at, t0}

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

        # Flat function_call events
        if evt == "function_call":
            _record_call(obj.get("call_id", ""), obj.get("name", ""), obj.get("arguments", "{}"))
        elif evt == "function_call_output":
            _record_result(obj.get("call_id", ""), obj.get("output", ""))

        # Nested response.output_item.added events (newer codex)
        elif evt == "response.output_item.added":
            item = obj.get("item") or {}
            if item.get("type") == "function_call":
                _record_call(item.get("call_id", ""), item.get("name", ""), item.get("arguments", "{}"))
            elif item.get("type") == "function_call_output":
                _record_result(item.get("call_id", ""), item.get("output", ""))

        # Generic: any dict with name + arguments that looks like a tool call
        elif "name" in obj and "arguments" in obj and "call_id" in obj:
            _record_call(obj["call_id"], obj["name"], obj["arguments"])

    return traces


def _call_openai(
    *,
    model_id: str,
    api_key: str | None,
    system_prompt: str,
    user_prompt: str,
    cfg: RunConfig,
    tool_schemas: list[dict[str, Any]] | None = None,
    tool_handlers: dict[str, Any] | None = None,
    max_tool_turns: int = 8,
) -> LLMResult:
    """Route to Responses API + MCP (when tools requested) or Chat Completions (no tools)."""
    if tool_schemas:
        return _call_openai_with_mcp(
            model_id=model_id, api_key=api_key,
            system_prompt=system_prompt, user_prompt=user_prompt,
            cfg=cfg, max_tool_turns=max_tool_turns,
        )
    return _call_openai_chat(
        model_id=model_id, api_key=api_key,
        system_prompt=system_prompt, user_prompt=user_prompt,
        cfg=cfg,
    )


def _call_openai_with_mcp(
    *,
    model_id: str,
    api_key: str | None,
    system_prompt: str,
    user_prompt: str,
    cfg: RunConfig,
    max_tool_turns: int = 8,
) -> LLMResult:
    """Tool-calling via OpenAI Responses API + native MCP connection.

    Points at the live VoltSnip MCP HTTP endpoint ({voltsnip_base_url}/mcp).
    OpenAI handles the entire tool loop server-side — no Python-side dispatch needed.
    Mirrors the claudecode MCP path but uses the OpenAI Responses API.
    """
    try:
        from openai import OpenAI
    except ImportError as exc:
        raise ImportError("openai package required: pip install openai") from exc

    client = OpenAI(api_key=api_key or os.environ.get("OPENAI_API_KEY"))
    t0 = datetime.now(timezone.utc)
    perf0 = time.perf_counter()

    base_url = (cfg.voltsnip_base_url or "http://localhost:8001").rstrip("/")
    # Use trailing slash to avoid FastAPI 307 redirect /mcp -> /mcp/.
    mcp_url = f"{base_url}/mcp/"

    kwargs: dict[str, Any] = {
        "model": model_id,
        "tools": [{"type": "mcp", "server_url": mcp_url, "server_label": "voltsnip"}],
        "input": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
    }
    if cfg.max_tokens:
        kwargs["max_output_tokens"] = cfg.max_tokens

    # OpenAI's servers call this URL — must be publicly accessible.
    if mcp_url.startswith(("http://localhost", "http://127.0.0.1", "http://0.0.0.0")):
        raise RuntimeError(
            f"openai Responses API + MCP requires a publicly accessible server, but "
            f"got {mcp_url!r}. Set VOLTSNIP_BASE_URL to the public API URL "
            f"(e.g. https://voltsnip-api.example.com) or use claudecode: for local runs."
        )

    LOGGER.debug("openai responses+mcp model=%s mcp_url=%s", model_id, mcp_url)
    try:
        resp = client.responses.create(**kwargs)
    except Exception as exc:
        raise RuntimeError(f"openai responses API call failed: {exc}") from exc

    final_content = getattr(resp, "output_text", "") or ""
    usage = getattr(resp, "usage", None)
    prompt_tokens = int(getattr(usage, "input_tokens", 0) or 0) if usage else 0
    completion_tokens = int(getattr(usage, "output_tokens", 0) or 0) if usage else 0
    request_id = getattr(resp, "id", None)
    # Reasoning tokens from Responses API (o-series and reasoning-enabled models)
    out_details = getattr(usage, "output_tokens_details", None) if usage else None
    thinking_tokens = _int_or_none(getattr(out_details, "reasoning_tokens", None) if out_details else None)

    parsed, fallback = _parse_payload(final_content, cfg.structured_output)
    return LLMResult(
        raw_output=final_content, parsed_output=parsed,
        token_usage=TokenUsage(
            prompt_tokens=prompt_tokens, completion_tokens=completion_tokens,
            total_tokens=prompt_tokens + completion_tokens,
            thinking_tokens=thinking_tokens,
            cost_usd=_compute_cost(model_id, prompt_tokens, completion_tokens),
        ),
        structured_output_attempted=cfg.structured_output,
        structured_output_succeeded=not fallback if cfg.structured_output else False,
        fallback_parser_used=fallback,
        request_started_at=t0, request_finished_at=datetime.now(timezone.utc),
        request_latency_ms=int((time.perf_counter() - perf0) * 1000),
        request_id=str(request_id) if request_id else None, finish_reason="stop",
    )


def _call_openai_chat(
    *,
    model_id: str,
    api_key: str | None,
    system_prompt: str,
    user_prompt: str,
    cfg: RunConfig,
) -> LLMResult:
    """Single-shot Chat Completions call (P0–P3: no tools)."""
    try:
        from openai import OpenAI
    except ImportError as exc:
        raise ImportError("openai package required: pip install openai") from exc

    client = OpenAI(api_key=api_key or os.environ.get("OPENAI_API_KEY"))
    t0 = datetime.now(timezone.utc)
    perf0 = time.perf_counter()

    kwargs: dict[str, Any] = {
        "model": model_id,
        "temperature": cfg.temperature,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
    }
    if cfg.max_tokens:
        kwargs["max_completion_tokens"] = cfg.max_tokens
    if cfg.structured_output:
        kwargs["response_format"] = {"type": "json_object"}

    LOGGER.debug("openai chat model=%s", model_id)
    try:
        resp = client.chat.completions.create(**kwargs)
    except Exception as exc:
        # Some newer OpenAI models (gpt-5-*) reject explicit temperature=0;
        # retry once without it to use the model default.
        if "temperature" in str(exc) and "unsupported_value" in str(exc):
            kwargs.pop("temperature", None)
            try:
                resp = client.chat.completions.create(**kwargs)
            except Exception as exc2:
                raise RuntimeError(f"openai call failed: {exc2}") from exc2
        else:
            raise RuntimeError(f"openai call failed: {exc}") from exc

    request_id = getattr(resp, "id", None)
    usage = getattr(resp, "usage", None)
    prompt_tokens = 0
    completion_tokens = 0
    cached_tokens = 0
    thinking_tokens: int | None = None
    if usage:
        prompt_tokens = getattr(usage, "prompt_tokens", 0) or 0
        completion_tokens = getattr(usage, "completion_tokens", 0) or 0
        # OpenAI automatic prompt caching (≥1024 token prefix, ~50% cost)
        details = getattr(usage, "prompt_tokens_details", None)
        cached_tokens = getattr(details, "cached_tokens", 0) or 0
        # Reasoning tokens: o-series and gpt-5 models with built-in reasoning
        ct_details = getattr(usage, "completion_tokens_details", None)
        thinking_tokens = _int_or_none(getattr(ct_details, "reasoning_tokens", None) if ct_details else None)

    choice = (resp.choices or [None])[0]
    finish_reason = getattr(choice, "finish_reason", None) if choice else None
    msg = getattr(choice, "message", None) if choice else None
    content = getattr(msg, "content", None) if msg else None
    final_content = ""
    if isinstance(content, str):
        final_content = content
    elif isinstance(content, list):
        final_content = "\n".join(str(b.get("text", "")) if isinstance(b, dict) else str(b) for b in content)

    parsed, fallback = _parse_payload(final_content, cfg.structured_output)
    return LLMResult(
        raw_output=final_content, parsed_output=parsed,
        token_usage=TokenUsage(
            prompt_tokens=prompt_tokens, completion_tokens=completion_tokens,
            total_tokens=prompt_tokens + completion_tokens,
            cached_tokens=cached_tokens,
            thinking_tokens=thinking_tokens,
            cost_usd=_compute_cost(model_id, prompt_tokens, completion_tokens),
        ),
        structured_output_attempted=cfg.structured_output,
        structured_output_succeeded=not fallback if cfg.structured_output else False,
        fallback_parser_used=fallback,
        request_started_at=t0, request_finished_at=datetime.now(timezone.utc),
        request_latency_ms=int((time.perf_counter() - perf0) * 1000),
        request_id=str(request_id) if request_id else None,
        finish_reason=str(finish_reason) if finish_reason else None,
    )


def _call_anthropic(
    *,
    model_id: str,
    api_key: str | None,
    system_prompt: str,
    user_prompt: str,
    cfg: RunConfig,
    tool_schemas: list[dict[str, Any]] | None = None,
    tool_handlers: dict[str, Any] | None = None,
    max_tool_turns: int = 8,
) -> LLMResult:
    try:
        from anthropic import Anthropic
    except ImportError as exc:
        raise ImportError("anthropic package required: pip install anthropic") from exc

    client = Anthropic(api_key=api_key or os.environ.get("ANTHROPIC_API_KEY"))
    t0 = datetime.now(timezone.utc)
    perf0 = time.perf_counter()

    messages: list[dict[str, Any]] = [{"role": "user", "content": user_prompt}]
    # Wrap system prompt as a content block with cache_control so Anthropic
    # caches the KV for up to 5 minutes.  The first call pays 1.25× write cost;
    # subsequent calls within the window pay 0.1× read cost.
    kwargs: dict[str, Any] = {
        "model": model_id,
        "system": [{"type": "text", "text": system_prompt, "cache_control": {"type": "ephemeral"}}],
        "messages": messages,
        "max_tokens": cfg.max_tokens or 4096,
        "temperature": cfg.temperature,
    }
    if tool_schemas:
        # Convert from OpenAI-style to Anthropic tool format
        anthropic_tools = [_openai_tool_to_anthropic(t) for t in tool_schemas]
        kwargs["tools"] = anthropic_tools

    total_input = 0
    total_output = 0
    total_cached = 0
    total_thinking: int | None = None
    final_content = ""
    finish_reason = None
    request_id = None

    for _turn in range(max(1, max_tool_turns)):
        LOGGER.debug("anthropic call model=%s turn=%d messages=%d", model_id, _turn, len(messages))
        try:
            resp = client.messages.create(**kwargs)
        except Exception as exc:
            raise RuntimeError(f"anthropic call failed: {exc}") from exc

        request_id = getattr(resp, "id", None)
        usage = getattr(resp, "usage", None)
        if usage:
            total_input += getattr(usage, "input_tokens", 0) or 0
            total_output += getattr(usage, "output_tokens", 0) or 0
            # cache_read_input_tokens = tokens served from prompt cache (0.1× cost)
            total_cached += getattr(usage, "cache_read_input_tokens", 0) or 0
            # Extended thinking tokens (Anthropic thinking API, if enabled)
            tt = _int_or_none(getattr(usage, "thinking_tokens", None))
            if tt is not None:
                total_thinking = (total_thinking or 0) + tt

        stop_reason = getattr(resp, "stop_reason", None)
        finish_reason = str(stop_reason) if stop_reason else None
        content_blocks = resp.content if hasattr(resp, "content") else []

        # Collect tool_use blocks and text blocks
        tool_use_blocks = [b for b in content_blocks if getattr(b, "type", None) == "tool_use"]
        text_blocks = [b for b in content_blocks if getattr(b, "type", None) == "text"]

        if tool_use_blocks and tool_handlers and stop_reason == "tool_use":
            # Append assistant turn with all content blocks
            messages.append({"role": "assistant", "content": [
                {"type": "tool_use", "id": b.id, "name": b.name, "input": b.input}
                if getattr(b, "type", None) == "tool_use"
                else {"type": "text", "text": getattr(b, "text", "")}
                for b in content_blocks
            ]})
            # Build tool_result turn
            tool_results: list[dict[str, Any]] = []
            for block in tool_use_blocks:
                handler = tool_handlers.get(block.name)
                if handler:
                    try:
                        tool_result = handler(block.input or {})
                        result_content = json.dumps(tool_result, ensure_ascii=False)
                    except Exception as e:
                        result_content = json.dumps({"error": str(e)})
                else:
                    result_content = json.dumps({"error": f"unknown tool {block.name}"})
                tool_results.append({"type": "tool_result", "tool_use_id": block.id, "content": result_content})
            messages.append({"role": "user", "content": tool_results})
            kwargs["messages"] = messages
            continue

        # Final text response
        final_content = "\n".join(getattr(b, "text", "") for b in text_blocks if hasattr(b, "text")).strip()
        break

    parsed, fallback = _parse_payload(final_content, cfg.structured_output)
    return LLMResult(
        raw_output=final_content, parsed_output=parsed,
        token_usage=TokenUsage(
            prompt_tokens=total_input, completion_tokens=total_output,
            total_tokens=total_input + total_output,
            cached_tokens=total_cached,
            thinking_tokens=total_thinking,
            cost_usd=_compute_cost(model_id, total_input, total_output),
        ),
        structured_output_attempted=cfg.structured_output,
        structured_output_succeeded=not fallback if cfg.structured_output else False,
        fallback_parser_used=fallback,
        request_started_at=t0, request_finished_at=datetime.now(timezone.utc),
        request_latency_ms=int((time.perf_counter() - perf0) * 1000),
        request_id=str(request_id) if request_id else None, finish_reason=finish_reason,
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _int_or_none(val: object) -> int | None:
    """Convert to int or return None (handles 0, "", None, False gracefully)."""
    if val is None or val == "" or val is False:
        return None
    try:
        result = int(val)  # type: ignore[arg-type]
        return result if result > 0 else None
    except (TypeError, ValueError):
        return None


def _parse_model(model_name: str) -> tuple[str, str]:
    """Return (provider, model_id) from 'provider:model_id'."""
    if ":" in model_name:
        provider, model_id = model_name.split(":", 1)
    else:
        provider, model_id = "openai", model_name
    norm = {
        "openai": "openai", "anthropic": "anthropic",
        "claudecode": "claudecode", "codex": "codex", "mock": "mock",
    }.get(provider.strip().lower(), provider.strip().lower())
    return norm, model_id.strip()


def _resolve_key(provider: str, cfg: RunConfig, provider_keys: dict[str, str]) -> str | None:
    if cfg.api_key:
        return cfg.api_key
    if provider in cfg.provider_api_keys:
        return cfg.provider_api_keys[provider]
    if provider in provider_keys:
        return provider_keys[provider]
    env_map = {"openai": "OPENAI_API_KEY", "anthropic": "ANTHROPIC_API_KEY"}
    env_key = env_map.get(provider)
    if env_key:
        return os.environ.get(env_key)
    return None


def _parse_payload(raw: str, structured_output: bool) -> tuple[GeneratedPayload, bool]:
    """Try to parse model output as JSON {code, comments}. Returns (payload, fallback_used)."""
    text = raw.strip()
    if not text:
        return GeneratedPayload(code="", comments=""), True

    # Direct JSON parse
    obj = _try_json(text)
    if obj and isinstance(obj.get("code"), str):
        return GeneratedPayload(code=obj["code"], comments=obj.get("comments") or ""), False

    # Scan for JSON objects
    for candidate in reversed(_json_candidates(text)):
        obj = _try_json(candidate)
        if obj and isinstance(obj.get("code"), str):
            return GeneratedPayload(code=obj["code"], comments=obj.get("comments") or ""), True

    # Fallback: extract code fence
    code, comments = "", ""
    fence = re.search(r"```(?:\w+)?\n([\s\S]*?)\n```", text)
    if fence:
        code = fence.group(1).strip()
    cmatch = re.search(r"comments\s*[:=]\s*([\s\S]+)", text, re.IGNORECASE)
    if cmatch:
        comments = cmatch.group(1).strip()
    return GeneratedPayload(code=code, comments=comments), True


def _try_json(text: str) -> dict | None:
    try:
        obj = json.loads(text)
        return obj if isinstance(obj, dict) else None
    except Exception:
        return None


def _json_candidates(text: str) -> list[str]:
    """Extract all top-level JSON object substrings from text."""
    candidates: list[str] = []
    depth = 0
    start: int | None = None
    in_str = False
    escaped = False
    for i, ch in enumerate(text):
        if in_str:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
            continue
        if ch == "{":
            if depth == 0:
                start = i
            depth += 1
        elif ch == "}" and depth > 0:
            depth -= 1
            if depth == 0 and start is not None:
                candidates.append(text[start:i + 1])
                start = None
    return candidates


def _openai_tool_to_anthropic(tool: dict[str, Any]) -> dict[str, Any]:
    """Convert OpenAI function tool schema to Anthropic tool schema."""
    fn = tool.get("function", {})
    return {
        "name": fn.get("name", ""),
        "description": fn.get("description", ""),
        "input_schema": fn.get("parameters", {"type": "object", "properties": {}}),
    }


# --- Tool schemas (shared for P4–P6a tool variants) ------------------------------------


def voltsnip_tool_schemas() -> list[dict[str, Any]]:
    """Return OpenAI-format tool schemas for VoltSnip tools."""
    return [
        {
            "type": "function",
            "function": {
                "name": "voltsnip_fetch_by_canonical_keys",
                "description": "Fetch snippets by canonical keys from VoltSnip.",
                "parameters": {
                    "type": "object",
                    "properties": {"canonical_keys": {"type": "array", "items": {"type": "string"}}},
                    "required": ["canonical_keys"],
                    "additionalProperties": False,
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "voltsnip_semantic_search",
                "description": "Run semantic search against VoltSnip snippets.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string"},
                        "k": {"type": "integer", "minimum": 1, "maximum": 50},
                    },
                    "required": ["query"],
                    "additionalProperties": False,
                },
            },
        },
    ]
