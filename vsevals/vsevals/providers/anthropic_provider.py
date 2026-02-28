import json
import logging
import os
import time
from datetime import datetime, timezone
from typing import Any

from vsevals.models import RunConfig, TokenUsage, LLMResult, compute_cost
from . import _parse_payload, _safe_response_json, _int_or_none

LOGGER = logging.getLogger(__name__)

def _openai_tool_to_anthropic(tool: dict[str, Any]) -> dict[str, Any]:
    fn = tool.get("function", {})
    return {
        "name": fn.get("name", ""),
        "description": fn.get("description", ""),
        "input_schema": fn.get("parameters", {"type": "object", "properties": {}}),
    }

def call_anthropic(
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
    kwargs: dict[str, Any] = {
        "model": model_id,
        "system": system_prompt,
        "messages": messages,
        "max_tokens": cfg.max_tokens or 4096,
        "temperature": cfg.temperature,
    }
    if tool_schemas:
        kwargs["tools"] = [_openai_tool_to_anthropic(t) for t in tool_schemas]

    total_input = 0
    total_output = 0
    total_cached = 0
    total_thinking = None
    final_content = ""
    finish_reason = None
    request_id = None
    api_response_parts: list[str] = []

    for _turn in range(max(1, max_tool_turns)):
        LOGGER.debug("anthropic call model=%s turn=%d messages=%d", model_id, _turn, len(messages))
        try:
            resp = client.messages.create(**kwargs)
        except Exception as exc:
            raise RuntimeError(f"anthropic call failed: {exc}") from exc

        api_response_parts.append(_safe_response_json(resp))
        request_id = getattr(resp, "id", None)
        usage = getattr(resp, "usage", None)
        if usage:
            total_input += getattr(usage, "input_tokens", 0) or 0
            total_output += getattr(usage, "output_tokens", 0) or 0
            total_cached += getattr(usage, "cache_read_input_tokens", 0) or 0
            tt = _int_or_none(getattr(usage, "thinking_tokens", None))
            if tt is not None:
                total_thinking = (total_thinking or 0) + tt

        stop_reason = getattr(resp, "stop_reason", None)
        finish_reason = str(stop_reason) if stop_reason else None
        content_blocks = resp.content if hasattr(resp, "content") else []

        tool_use_blocks = [b for b in content_blocks if getattr(b, "type", None) == "tool_use"]
        text_blocks = [b for b in content_blocks if getattr(b, "type", None) == "text"]

        if tool_use_blocks and tool_handlers and stop_reason == "tool_use":
            messages.append({"role": "assistant", "content": [
                {"type": "tool_use", "id": b.id, "name": b.name, "input": b.input}
                if getattr(b, "type", None) == "tool_use"
                else {"type": "text", "text": getattr(b, "text", "")}
                for b in content_blocks
            ]})
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

        final_content = "\n".join(getattr(b, "text", "") for b in text_blocks if hasattr(b, "text")).strip()
        break

    if len(api_response_parts) == 1:
        api_response_raw_val = api_response_parts[0]
    elif api_response_parts:
        api_response_raw_val = "[" + ",".join(api_response_parts) + "]"
    else:
        api_response_raw_val = ""

    parsed, fallback = _parse_payload(final_content, cfg.structured_output)
    return LLMResult(
        raw_output=final_content, 
        parsed_output=parsed,
        token_usage=TokenUsage(
            prompt_tokens=total_input, completion_tokens=total_output,
            total_tokens=total_input + total_output,
            cached_tokens=total_cached,
            thinking_tokens=total_thinking,
            cost_usd=compute_cost(model_id, total_input, total_output, total_cached),
        ),
        structured_output_attempted=cfg.structured_output,
        structured_output_succeeded=not fallback if cfg.structured_output else False,
        fallback_parser_used=fallback,
        request_started_at=t0, request_finished_at=datetime.now(timezone.utc),
        request_latency_ms=int((time.perf_counter() - perf0) * 1000),
        request_id=str(request_id) if request_id else None, finish_reason=finish_reason,
        api_response_raw=api_response_raw_val,
    )
