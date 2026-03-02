"""LLM dispatch layer — routes to the appropriate provider.

Providers
---------
claudecode   → `claude -p` subprocess (Claude Code stored auth; no API key needed)
             P4-P6: writes temp --mcp-config JSON pointing at VoltSnip MCP HTTP
             endpoint. Works with localhost.
codex        → `codex exec` subprocess (Codex CLI stored auth; no API key needed)
             P4-P6: injects MCP server per-run via -c mcp_servers.voltsnip.*
             Works with localhost.
anthropic    → Anthropic Python SDK (requires ANTHROPIC_API_KEY or provider_keys)
openai       → OpenAI Python SDK (requires OPENAI_API_KEY or provider_keys)
             P4-P6 with tools: uses Responses API + MCP (public URL required).
mock         → In-memory echo stub (tests/smoke only; no API key needed)

Entry point
-----------
    result = call_llm(
        model_name="claudecode:haiku-4-5",
        system_prompt=...,
        user_prompt=...,
        cfg=RunConfig(...),
        provider_keys={},
        tool_schemas=[...],   # optional — enables tool loop
        max_tool_turns=8,     # optional
    )

Judge entry point
-----------------
    raw_text = call_judge(
        model_name="anthropic:claude-opus-4-6",
        system_prompt=...,
        user_prompt=...,
        cfg=RunConfig(...),
        provider_keys={},
    )
"""

from __future__ import annotations

import logging
from typing import Any

from vsevals.models import RunConfig, LLMResult, parse_model

LOGGER = logging.getLogger(__name__)


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
    repo_root: str | None = None,
) -> LLMResult:
    """Dispatch an LLM call to the appropriate provider."""
    provider, model_id = parse_model(model_name)

    if provider == "claudecode":
        from .providers.claudecode import call_claudecode
        return call_claudecode(
            model_id=model_id,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            cfg=cfg,
            tool_schemas=tool_schemas,
            max_tool_turns=max_tool_turns,
            sidecar_files=sidecar_files,
            repo_root=repo_root,
        )

    elif provider == "codex":
        from .providers.codex import call_codex
        return call_codex(
            model_id=model_id,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            cfg=cfg,
            tool_schemas=tool_schemas,
            max_tool_turns=max_tool_turns,
            sidecar_files=sidecar_files,
            repo_root=repo_root,
        )

    elif provider == "anthropic":
        from .providers.anthropic_provider import call_anthropic
        return call_anthropic(
            model_id=model_id,
            api_key=provider_keys.get("anthropic") or cfg.api_key,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            cfg=cfg,
            tool_schemas=tool_schemas,
            tool_handlers=tool_handlers,
            max_tool_turns=max_tool_turns,
        )

    elif provider == "openai":
        from .providers.openai import call_openai
        return call_openai(
            model_id=model_id,
            api_key=provider_keys.get("openai") or cfg.api_key,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            cfg=cfg,
            tool_schemas=tool_schemas,
            tool_handlers=tool_handlers,
            max_tool_turns=max_tool_turns,
        )

    elif provider == "mock":
        from .providers.mock import call_mock
        return call_mock(
            model_id=model_id,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            cfg=cfg,
        )

    else:
        raise ValueError(
            f"unsupported provider '{provider}' in model '{model_name}' "
            f"(supported: claudecode, codex, anthropic, openai, mock)"
        )


def call_judge(
    *,
    model_name: str,
    system_prompt: str,
    user_prompt: str,
    cfg: RunConfig,
    provider_keys: dict[str, str],
) -> str:
    """Judge calls (single-shot, no structured output, no tools).

    Ensemble judge specs like "openai:gpt-5.2+anthropic:claude-opus-4-6" are
    parsed and dispatched by scorer.py; this function handles one model at a time.
    """
    judge_cfg = cfg.model_copy()
    judge_cfg.structured_output = False
    judge_cfg.temperature = None  # reasoning/latest-gen models reject temperature

    provider, model_id = parse_model(model_name)

    if provider == "claudecode":
        from .providers.claudecode import call_claudecode
        res = call_claudecode(
            model_id=model_id, system_prompt=system_prompt, user_prompt=user_prompt,
            cfg=judge_cfg, tool_schemas=None,
        )
        return res.raw_output

    elif provider == "codex":
        from .providers.codex import call_codex
        res = call_codex(
            model_id=model_id, system_prompt=system_prompt, user_prompt=user_prompt,
            cfg=judge_cfg, tool_schemas=None,
        )
        return res.raw_output

    elif provider == "anthropic":
        from .providers.anthropic_provider import call_anthropic
        res = call_anthropic(
            model_id=model_id,
            api_key=provider_keys.get("anthropic") or cfg.api_key,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            cfg=judge_cfg,
            tool_schemas=None,
        )
        return res.raw_output

    elif provider == "openai":
        from .providers.openai import call_openai_chat
        res = call_openai_chat(
            model_id=model_id,
            api_key=provider_keys.get("openai") or cfg.api_key,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            cfg=judge_cfg,
        )
        return res.raw_output

    elif provider == "mock":
        from .providers.mock import call_mock
        res = call_mock(
            model_id=model_id, system_prompt=system_prompt,
            user_prompt=user_prompt, cfg=judge_cfg,
        )
        return res.raw_output

    else:
        raise ValueError(
            f"unsupported judge provider '{provider}' "
            f"(supported: claudecode, codex, anthropic, openai, mock)"
        )


def harness_tool_schemas() -> list[dict[str, Any]]:
    """JSON schemas for all eval harness tools.

    Covers both filesystem tools (read_file, glob_files, grep_files) and
    VoltSnip tools (search_memory, get_snippet_by_canonical_key).

    For claudecode: filesystem tools are built-ins (Read/Glob/Grep); VoltSnip
    tools are served by the VoltSnip MCP endpoint.
    For codex: all harness MCP tools are served by HarnessMCPServer started per-run.
    """
    return [
        {
            "type": "function",
            "function": {
                "name": "read_file",
                "description": "Read file contents at a path relative to repo root.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string"},
                        "offset": {"type": "integer"},
                        "limit": {"type": "integer"},
                    },
                    "required": ["path"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "glob_files",
                "description": "Find files matching a glob pattern in the repo.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "pattern": {"type": "string"},
                    },
                    "required": ["pattern"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "grep_files",
                "description": "Search file contents using a regex pattern.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "pattern": {"type": "string"},
                        "path": {"type": "string"},
                        "glob": {"type": "string"},
                    },
                    "required": ["pattern"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "search_memory",
                "description": "Semantic search for reusable code patterns.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string"},
                        "intent": {"type": "string"},
                        "language": {"type": "string"},
                        "tags": {"type": "array", "items": {"type": "string"}},
                    },
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "get_snippet_by_canonical_key",
                "description": "Fetch a specific snippet directly by its canonical key.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "key": {"type": "string"},
                    },
                    "required": ["key"],
                },
            },
        },
    ]


# Backward-compat aliases — callers can use the unified function instead.
def filesystem_tool_schemas() -> list[dict[str, Any]]:
    return harness_tool_schemas()[:3]


def voltsnip_tool_schemas() -> list[dict[str, Any]]:
    return harness_tool_schemas()[3:]
