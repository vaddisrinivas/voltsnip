"""LLM dispatch layer — routes to the appropriate provider.

Providers
---------
claudecode   → `claude -p` subprocess (Claude Code stored auth; no API key needed)
codex        → `codex exec` subprocess (Codex CLI stored auth; no API key needed)
anthropic    → Anthropic Python SDK (requires ANTHROPIC_API_KEY or provider_keys)
openai       → OpenAI Python SDK (requires OPENAI_API_KEY or provider_keys)
mock         → In-memory echo stub (tests/smoke only; no API key needed)
"""

from __future__ import annotations

import logging
from typing import Any

from vsevals.models import RunConfig, LLMResult, parse_model

LOGGER = logging.getLogger(__name__)


def _dispatch(
    *,
    provider: str,
    model_id: str,
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
    judge_mode: bool = False,
) -> LLMResult:
    if provider == "claudecode":
        from .providers.claudecode import call_claudecode
        return call_claudecode(
            model_id=model_id, system_prompt=system_prompt, user_prompt=user_prompt,
            cfg=cfg, tool_schemas=tool_schemas, max_tool_turns=max_tool_turns,
            sidecar_files=sidecar_files, repo_root=repo_root,
        )
    if provider == "codex":
        from .providers.codex import call_codex
        return call_codex(
            model_id=model_id, system_prompt=system_prompt, user_prompt=user_prompt,
            cfg=cfg, tool_schemas=tool_schemas, max_tool_turns=max_tool_turns,
            sidecar_files=sidecar_files, repo_root=repo_root,
        )
    if provider == "anthropic":
        from .providers.anthropic_provider import call_anthropic
        return call_anthropic(
            model_id=model_id, api_key=provider_keys.get("anthropic") or cfg.api_key,
            system_prompt=system_prompt, user_prompt=user_prompt, cfg=cfg,
            tool_schemas=tool_schemas, tool_handlers=tool_handlers, max_tool_turns=max_tool_turns,
        )
    if provider == "openai":
        if judge_mode:
            from .providers.openai import call_openai_chat
            return call_openai_chat(
                model_id=model_id, api_key=provider_keys.get("openai") or cfg.api_key,
                system_prompt=system_prompt, user_prompt=user_prompt, cfg=cfg,
            )
        from .providers.openai import call_openai
        return call_openai(
            model_id=model_id, api_key=provider_keys.get("openai") or cfg.api_key,
            system_prompt=system_prompt, user_prompt=user_prompt, cfg=cfg,
            tool_schemas=tool_schemas, tool_handlers=tool_handlers, max_tool_turns=max_tool_turns,
        )
    if provider == "mock":
        from .providers.mock import call_mock
        return call_mock(
            model_id=model_id, system_prompt=system_prompt, user_prompt=user_prompt, cfg=cfg,
        )
    raise ValueError(
        f"unsupported provider '{provider}' in model '{model_name}' "
        f"(supported: claudecode, codex, anthropic, openai, mock)"
    )


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
    return _dispatch(
        provider=provider, model_id=model_id, model_name=model_name,
        system_prompt=system_prompt, user_prompt=user_prompt,
        cfg=cfg, provider_keys=provider_keys,
        tool_schemas=tool_schemas, tool_handlers=tool_handlers,
        max_tool_turns=max_tool_turns, sidecar_files=sidecar_files, repo_root=repo_root,
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
    res = _dispatch(
        provider=provider, model_id=model_id, model_name=model_name,
        system_prompt=system_prompt, user_prompt=user_prompt,
        cfg=judge_cfg, provider_keys=provider_keys,
        tool_schemas=None, judge_mode=True,
    )
    return res.raw_output


def harness_tool_schemas() -> list[dict[str, Any]]:
    """JSON schemas for all eval harness tools."""
    def _fn(name: str, description: str, props: dict, required: list[str] | None = None) -> dict:
        schema: dict = {"type": "object", "properties": props}
        if required:
            schema["required"] = required
        return {"type": "function", "function": {"name": name, "description": description, "parameters": schema}}

    return [
        _fn("read_file", "Read file contents at a path relative to repo root.",
            {"path": {"type": "string"}, "offset": {"type": "integer"}, "limit": {"type": "integer"}},
            ["path"]),
        _fn("glob_files", "Find files matching a glob pattern in the repo.",
            {"pattern": {"type": "string"}}, ["pattern"]),
        _fn("grep_files", "Search file contents using a regex pattern.",
            {"pattern": {"type": "string"}, "path": {"type": "string"}, "glob": {"type": "string"}},
            ["pattern"]),
        _fn("search_memory", "Semantic search for reusable code patterns.",
            {"query": {"type": "string"}, "intent": {"type": "string"},
             "language": {"type": "string"}, "tags": {"type": "array", "items": {"type": "string"}}}),
        _fn("get_snippet_by_canonical_key", "Fetch a specific snippet directly by its canonical key.",
            {"key": {"type": "string"}}, ["key"]),
    ]


# Backward-compat aliases
def filesystem_tool_schemas() -> list[dict[str, Any]]:
    return harness_tool_schemas()[:3]


def voltsnip_tool_schemas() -> list[dict[str, Any]]:
    return harness_tool_schemas()[3:]
