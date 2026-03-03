import logging
import os
import time
from datetime import datetime, timezone
from typing import Any

from vsevals.models import RunConfig, TokenUsage, LLMResult, compute_cost
from . import _parse_payload, _safe_response_json, _int_or_none

LOGGER = logging.getLogger(__name__)

def call_openai_chat(
    *,
    model_id: str,
    api_key: str | None,
    system_prompt: str,
    user_prompt: str,
    cfg: RunConfig,
) -> LLMResult:
    try:
        from openai import OpenAI
    except ImportError as exc:
        raise ImportError("openai package required: pip install openai") from exc

    client = OpenAI(api_key=api_key or os.environ.get("OPENAI_API_KEY"))
    t0 = datetime.now(timezone.utc)
    perf0 = time.perf_counter()

    system_content = system_prompt
    if cfg.structured_output:
        system_content = system_content.rstrip() + "\n\nYou must output valid JSON."

    kwargs: dict[str, Any] = {
        "model": model_id,
        "messages": [
            {"role": "system", "content": system_content},
            {"role": "user", "content": user_prompt},
        ],
    }
    if cfg.temperature is not None:
        kwargs["temperature"] = cfg.temperature
    if cfg.max_tokens:
        kwargs["max_completion_tokens"] = cfg.max_tokens
    if cfg.structured_output:
        kwargs["response_format"] = {"type": "json_object"}
    if cfg.reasoning_effort:
        kwargs["reasoning_effort"] = cfg.reasoning_effort

    LOGGER.debug("openai chat model=%s", model_id)
    try:
        resp = client.chat.completions.create(**kwargs)
    except Exception as exc:
        exc_str = str(exc).lower()
        if "temperature" in exc_str:
            # Some models (reasoning / latest-gen) don't support temperature at all.
            # Retry without it — covers "unsupported_value", "not supported",
            # "parameter not allowed", and any other temperature-related 400.
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
    thinking_tokens = None
    if usage:
        prompt_tokens = getattr(usage, "prompt_tokens", 0) or 0
        completion_tokens = getattr(usage, "completion_tokens", 0) or 0
        details = getattr(usage, "prompt_tokens_details", None)
        cached_tokens = getattr(details, "cached_tokens", 0) or 0
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
        raw_output=final_content, 
        parsed_output=parsed,
        token_usage=TokenUsage(
            prompt_tokens=prompt_tokens, completion_tokens=completion_tokens,
            total_tokens=prompt_tokens + completion_tokens,
            cached_tokens=cached_tokens,
            thinking_tokens=thinking_tokens,
            cost_usd=compute_cost(model_id, prompt_tokens, completion_tokens, cached_tokens),
        ),
        structured_output_attempted=cfg.structured_output,
        structured_output_succeeded=not fallback if cfg.structured_output else False,
        fallback_parser_used=fallback,
        request_started_at=t0, request_finished_at=datetime.now(timezone.utc),
        request_latency_ms=int((time.perf_counter() - perf0) * 1000),
        request_id=str(request_id) if request_id else None,
        finish_reason=str(finish_reason) if finish_reason else None,
        api_response_raw=_safe_response_json(resp),
    )


def call_openai_with_mcp(
    *,
    model_id: str,
    api_key: str | None,
    system_prompt: str,
    user_prompt: str,
    cfg: RunConfig,
    max_tool_turns: int = 8,
) -> LLMResult:
    try:
        from openai import OpenAI
    except ImportError as exc:
        raise ImportError("openai package required: pip install openai") from exc

    client = OpenAI(api_key=api_key or os.environ.get("OPENAI_API_KEY"))
    t0 = datetime.now(timezone.utc)
    perf0 = time.perf_counter()

    base_url = (cfg.voltsnip_base_url or "http://localhost:8011").rstrip("/")
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

    if mcp_url.startswith(("http://localhost", "http://127.0.0.1", "http://0.0.0.0")):
        raise RuntimeError(
            f"openai Responses API + MCP requires a publicly accessible server, but got {mcp_url!r}."
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
    in_details = getattr(usage, "input_tokens_details", None) if usage else None
    cached_tokens = int(getattr(in_details, "cached_tokens", 0) or 0) if in_details else 0
    out_details = getattr(usage, "output_tokens_details", None) if usage else None
    thinking_tokens = _int_or_none(getattr(out_details, "reasoning_tokens", None) if out_details else None)

    parsed, fallback = _parse_payload(final_content, cfg.structured_output)
    return LLMResult(
        raw_output=final_content, 
        parsed_output=parsed,
        token_usage=TokenUsage(
            prompt_tokens=prompt_tokens, completion_tokens=completion_tokens,
            total_tokens=prompt_tokens + completion_tokens,
            cached_tokens=cached_tokens,
            thinking_tokens=thinking_tokens,
            cost_usd=compute_cost(model_id, prompt_tokens, completion_tokens, cached_tokens),
        ),
        structured_output_attempted=cfg.structured_output,
        structured_output_succeeded=not fallback if cfg.structured_output else False,
        fallback_parser_used=fallback,
        request_started_at=t0, request_finished_at=datetime.now(timezone.utc),
        request_latency_ms=int((time.perf_counter() - perf0) * 1000),
        request_id=str(request_id) if request_id else None, 
        finish_reason="stop",
        api_response_raw=_safe_response_json(resp),
    )

def call_openai(*, model_id: str, api_key: str | None, system_prompt: str, user_prompt: str, cfg: RunConfig, tool_schemas: list[dict[str, Any]] | None = None, tool_handlers: dict[str, Any] | None = None, max_tool_turns: int = 8) -> LLMResult:
    if tool_schemas:
         return call_openai_with_mcp(model_id=model_id, api_key=api_key, system_prompt=system_prompt, user_prompt=user_prompt, cfg=cfg, max_tool_turns=max_tool_turns)
    return call_openai_chat(model_id=model_id, api_key=api_key, system_prompt=system_prompt, user_prompt=user_prompt, cfg=cfg)

