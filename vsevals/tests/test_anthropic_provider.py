"""Tests for vsevals.providers.anthropic_provider — Anthropic Messages API with tool loop."""

from __future__ import annotations

import json
import sys
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from vsevals.models import RunConfig, LLMResult


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_text_block(text="hello"):
    return SimpleNamespace(type="text", text=text)


def _make_tool_use_block(tool_id="tu-1", name="search_snippets", input_data=None):
    return SimpleNamespace(
        type="tool_use",
        id=tool_id,
        name=name,
        input=input_data or {"query": "test"},
    )


def _make_usage(input_tokens=10, output_tokens=20, cache_read=0, thinking=None):
    return SimpleNamespace(
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cache_read_input_tokens=cache_read,
        thinking_tokens=thinking,
    )


def _make_response(
    content=None,
    stop_reason="end_turn",
    usage=None,
    request_id="msg-1",
):
    """Build a mock Anthropic Messages response."""
    if content is None:
        content = [_make_text_block("hello")]
    resp = MagicMock()
    resp.id = request_id
    resp.content = content
    resp.stop_reason = stop_reason
    resp.usage = usage or _make_usage()
    resp.model_dump_json.return_value = '{"id":"msg-1"}'
    return resp


def _cfg(**overrides) -> RunConfig:
    defaults = dict(
        api_key="sk-ant-test",
        structured_output=False,
    )
    defaults.update(overrides)
    return RunConfig(**defaults)


def _tool_schema(name="search_snippets", description="Search", params=None):
    return {
        "function": {
            "name": name,
            "description": description,
            "parameters": params or {"type": "object", "properties": {"query": {"type": "string"}}},
        }
    }


def _patch_anthropic():
    """Return a patch context that injects a mock Anthropic class into the anthropic module."""
    mock_anthropic_module = MagicMock()
    mock_client = MagicMock()
    mock_anthropic_module.Anthropic.return_value = mock_client
    return patch.dict(sys.modules, {"anthropic": mock_anthropic_module}), mock_client


# ---------------------------------------------------------------------------
# _openai_tool_to_anthropic — basic conversion
# ---------------------------------------------------------------------------


def test_tool_conversion_basic():
    from vsevals.providers.anthropic_provider import _openai_tool_to_anthropic

    tool = {
        "function": {
            "name": "search_snippets",
            "description": "Search for code snippets",
            "parameters": {"type": "object", "properties": {"q": {"type": "string"}}},
        }
    }
    result = _openai_tool_to_anthropic(tool)
    assert result["name"] == "search_snippets"
    assert result["description"] == "Search for code snippets"
    assert result["input_schema"] == {"type": "object", "properties": {"q": {"type": "string"}}}


# ---------------------------------------------------------------------------
# _openai_tool_to_anthropic — missing fields
# ---------------------------------------------------------------------------


def test_tool_conversion_missing_fields():
    from vsevals.providers.anthropic_provider import _openai_tool_to_anthropic

    result = _openai_tool_to_anthropic({})
    assert result["name"] == ""
    assert result["description"] == ""
    assert result["input_schema"] == {"type": "object", "properties": {}}


def test_tool_conversion_partial_function():
    from vsevals.providers.anthropic_provider import _openai_tool_to_anthropic

    result = _openai_tool_to_anthropic({"function": {"name": "foo"}})
    assert result["name"] == "foo"
    assert result["description"] == ""
    assert result["input_schema"] == {"type": "object", "properties": {}}


# ---------------------------------------------------------------------------
# call_anthropic — basic call without tools
# ---------------------------------------------------------------------------


def test_basic_call_no_tools():
    patcher, client = _patch_anthropic()
    with patcher:
        client.messages.create.return_value = _make_response(
            content=[_make_text_block("the answer")],
        )

        from vsevals.providers.anthropic_provider import call_anthropic

        result = call_anthropic(
            model_id="claude-haiku-4-5",
            api_key="sk-ant-test",
            system_prompt="You are helpful.",
            user_prompt="Hi there.",
            cfg=_cfg(),
        )
    assert isinstance(result, LLMResult)
    assert result.raw_output == "the answer"
    assert result.request_id == "msg-1"
    assert result.finish_reason == "end_turn"


# ---------------------------------------------------------------------------
# call_anthropic — with temperature
# ---------------------------------------------------------------------------


def test_with_temperature():
    patcher, client = _patch_anthropic()
    with patcher:
        client.messages.create.return_value = _make_response()

        from vsevals.providers.anthropic_provider import call_anthropic

        call_anthropic(
            model_id="claude-haiku-4-5",
            api_key="sk-ant-test",
            system_prompt="sys",
            user_prompt="hi",
            cfg=_cfg(temperature=0.5),
        )
        kwargs = client.messages.create.call_args.kwargs
    assert kwargs["temperature"] == 0.5


# ---------------------------------------------------------------------------
# call_anthropic — thinking budget with reasoning_effort
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("effort,expected_budget", [
    ("low", 1024),
    ("medium", 5000),
    ("high", 16000),
])
def test_thinking_budget(effort, expected_budget):
    patcher, client = _patch_anthropic()
    with patcher:
        client.messages.create.return_value = _make_response()

        from vsevals.providers.anthropic_provider import call_anthropic

        call_anthropic(
            model_id="claude-sonnet-4-5",
            api_key="sk-ant-test",
            system_prompt="sys",
            user_prompt="hi",
            cfg=_cfg(reasoning_effort=effort),
        )
        kwargs = client.messages.create.call_args.kwargs
    assert kwargs["thinking"] == {"type": "enabled", "budget_tokens": expected_budget}
    assert kwargs["temperature"] == 1  # API requirement when thinking is enabled


# ---------------------------------------------------------------------------
# call_anthropic — no thinking (unknown reasoning_effort)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("effort", [None, "unknown", ""])
def test_no_thinking(effort):
    patcher, client = _patch_anthropic()
    with patcher:
        client.messages.create.return_value = _make_response()

        from vsevals.providers.anthropic_provider import call_anthropic

        call_anthropic(
            model_id="claude-haiku-4-5",
            api_key="sk-ant-test",
            system_prompt="sys",
            user_prompt="hi",
            cfg=_cfg(reasoning_effort=effort),
        )
        kwargs = client.messages.create.call_args.kwargs
    assert "thinking" not in kwargs


# ---------------------------------------------------------------------------
# call_anthropic — with tool_schemas but no tool_handlers (single-turn)
# ---------------------------------------------------------------------------


def test_tools_no_handlers():
    patcher, client = _patch_anthropic()
    with patcher:
        client.messages.create.return_value = _make_response(
            content=[_make_text_block("I found it")],
            stop_reason="end_turn",
        )

        from vsevals.providers.anthropic_provider import call_anthropic

        result = call_anthropic(
            model_id="claude-haiku-4-5",
            api_key="sk-ant-test",
            system_prompt="sys",
            user_prompt="hi",
            cfg=_cfg(),
            tool_schemas=[_tool_schema()],
        )
        kwargs = client.messages.create.call_args.kwargs
    assert result.raw_output == "I found it"
    # Verify tools were sent in kwargs
    assert "tools" in kwargs
    assert kwargs["tools"][0]["name"] == "search_snippets"


# ---------------------------------------------------------------------------
# call_anthropic — tool loop (tool_schemas + tool_handlers)
# ---------------------------------------------------------------------------


def test_tool_loop():
    patcher, client = _patch_anthropic()
    with patcher:
        # First call: model wants to use a tool
        first_resp = _make_response(
            content=[_make_tool_use_block("tu-1", "search_snippets", {"query": "emit"})],
            stop_reason="tool_use",
            usage=_make_usage(input_tokens=50, output_tokens=30),
            request_id="msg-1",
        )
        # Second call: model produces final text
        second_resp = _make_response(
            content=[_make_text_block("final answer")],
            stop_reason="end_turn",
            usage=_make_usage(input_tokens=80, output_tokens=40),
            request_id="msg-2",
        )
        client.messages.create.side_effect = [first_resp, second_resp]

        def mock_handler(inputs):
            return {"result": "snippet found"}

        from vsevals.providers.anthropic_provider import call_anthropic

        result = call_anthropic(
            model_id="claude-haiku-4-5",
            api_key="sk-ant-test",
            system_prompt="sys",
            user_prompt="hi",
            cfg=_cfg(),
            tool_schemas=[_tool_schema()],
            tool_handlers={"search_snippets": mock_handler},
        )
    assert result.raw_output == "final answer"
    assert client.messages.create.call_count == 2
    # Usage accumulated across turns
    assert result.token_usage.prompt_tokens == 130  # 50 + 80
    assert result.token_usage.completion_tokens == 70  # 30 + 40


# ---------------------------------------------------------------------------
# call_anthropic — tool handler raises exception
# ---------------------------------------------------------------------------


def test_tool_handler_error():
    patcher, client = _patch_anthropic()
    with patcher:
        first_resp = _make_response(
            content=[_make_tool_use_block("tu-1", "search_snippets", {"query": "x"})],
            stop_reason="tool_use",
        )
        second_resp = _make_response(
            content=[_make_text_block("handled error")],
            stop_reason="end_turn",
        )
        client.messages.create.side_effect = [first_resp, second_resp]

        def broken_handler(inputs):
            raise ValueError("connection timeout")

        from vsevals.providers.anthropic_provider import call_anthropic

        result = call_anthropic(
            model_id="claude-haiku-4-5",
            api_key="sk-ant-test",
            system_prompt="sys",
            user_prompt="hi",
            cfg=_cfg(),
            tool_schemas=[_tool_schema()],
            tool_handlers={"search_snippets": broken_handler},
        )
        # Verify the error was passed as tool_result content
        second_call_kwargs = client.messages.create.call_args_list[1].kwargs
    # The tool error is sent back to the model, which then produces final output
    assert result.raw_output == "handled error"
    tool_result_msg = second_call_kwargs["messages"][-1]
    tool_content = json.loads(tool_result_msg["content"][0]["content"])
    assert "error" in tool_content
    assert "connection timeout" in tool_content["error"]


# ---------------------------------------------------------------------------
# call_anthropic — unknown tool (handler not in dict)
# ---------------------------------------------------------------------------


def test_unknown_tool():
    patcher, client = _patch_anthropic()
    with patcher:
        first_resp = _make_response(
            content=[_make_tool_use_block("tu-1", "nonexistent_tool", {"x": 1})],
            stop_reason="tool_use",
        )
        second_resp = _make_response(
            content=[_make_text_block("ok")],
            stop_reason="end_turn",
        )
        client.messages.create.side_effect = [first_resp, second_resp]

        from vsevals.providers.anthropic_provider import call_anthropic

        result = call_anthropic(
            model_id="claude-haiku-4-5",
            api_key="sk-ant-test",
            system_prompt="sys",
            user_prompt="hi",
            cfg=_cfg(),
            tool_schemas=[_tool_schema()],
            tool_handlers={"search_snippets": lambda inp: {"r": "ok"}},
        )
        second_call_kwargs = client.messages.create.call_args_list[1].kwargs
    assert result.raw_output == "ok"
    tool_result_msg = second_call_kwargs["messages"][-1]
    tool_content = json.loads(tool_result_msg["content"][0]["content"])
    assert "error" in tool_content
    assert "unknown tool nonexistent_tool" in tool_content["error"]


# ---------------------------------------------------------------------------
# call_anthropic — usage accumulation across turns
# ---------------------------------------------------------------------------


def test_usage_accumulation():
    patcher, client = _patch_anthropic()
    with patcher:
        resp1 = _make_response(
            content=[_make_tool_use_block()],
            stop_reason="tool_use",
            usage=_make_usage(input_tokens=100, output_tokens=25, cache_read=5, thinking=10),
        )
        resp2 = _make_response(
            content=[_make_text_block("done")],
            stop_reason="end_turn",
            usage=_make_usage(input_tokens=200, output_tokens=50, cache_read=15, thinking=20),
        )
        client.messages.create.side_effect = [resp1, resp2]

        from vsevals.providers.anthropic_provider import call_anthropic

        result = call_anthropic(
            model_id="claude-haiku-4-5",
            api_key="sk-ant-test",
            system_prompt="sys",
            user_prompt="hi",
            cfg=_cfg(),
            tool_schemas=[_tool_schema()],
            tool_handlers={"search_snippets": lambda inp: {"ok": True}},
        )
    assert result.token_usage.prompt_tokens == 300
    assert result.token_usage.completion_tokens == 75
    assert result.token_usage.cached_tokens == 20
    assert result.token_usage.thinking_tokens == 30
    assert result.token_usage.total_tokens == 375


# ---------------------------------------------------------------------------
# call_anthropic — multiple text blocks concatenation
# ---------------------------------------------------------------------------


def test_multiple_text_blocks():
    patcher, client = _patch_anthropic()
    with patcher:
        client.messages.create.return_value = _make_response(
            content=[
                _make_text_block("part one"),
                _make_text_block("part two"),
                _make_text_block("part three"),
            ],
        )

        from vsevals.providers.anthropic_provider import call_anthropic

        result = call_anthropic(
            model_id="claude-haiku-4-5",
            api_key="sk-ant-test",
            system_prompt="sys",
            user_prompt="hi",
            cfg=_cfg(),
        )
    assert result.raw_output == "part one\npart two\npart three"


# ---------------------------------------------------------------------------
# call_anthropic — empty content blocks
# ---------------------------------------------------------------------------


def test_empty_content_blocks():
    patcher, client = _patch_anthropic()
    with patcher:
        client.messages.create.return_value = _make_response(content=[])

        from vsevals.providers.anthropic_provider import call_anthropic

        result = call_anthropic(
            model_id="claude-haiku-4-5",
            api_key="sk-ant-test",
            system_prompt="sys",
            user_prompt="hi",
            cfg=_cfg(),
        )
    assert result.raw_output == ""


# ---------------------------------------------------------------------------
# call_anthropic — import error for anthropic package
# ---------------------------------------------------------------------------


def test_import_error():
    from vsevals.providers.anthropic_provider import call_anthropic

    with patch.dict(sys.modules, {"anthropic": None}):
        with pytest.raises(ImportError, match="anthropic package required"):
            call_anthropic(
                model_id="claude-haiku-4-5",
                api_key="sk-ant-test",
                system_prompt="sys",
                user_prompt="hi",
                cfg=_cfg(),
            )


# ---------------------------------------------------------------------------
# call_anthropic — API call error
# ---------------------------------------------------------------------------


def test_api_call_error():
    patcher, client = _patch_anthropic()
    with patcher:
        client.messages.create.side_effect = Exception("server overloaded")

        from vsevals.providers.anthropic_provider import call_anthropic

        with pytest.raises(RuntimeError, match="anthropic call failed"):
            call_anthropic(
                model_id="claude-haiku-4-5",
                api_key="sk-ant-test",
                system_prompt="sys",
                user_prompt="hi",
                cfg=_cfg(),
            )


# ---------------------------------------------------------------------------
# call_anthropic — api_response_raw for single turn is plain string
# ---------------------------------------------------------------------------


def test_api_response_raw_single_turn():
    patcher, client = _patch_anthropic()
    with patcher:
        client.messages.create.return_value = _make_response()

        from vsevals.providers.anthropic_provider import call_anthropic

        result = call_anthropic(
            model_id="claude-haiku-4-5",
            api_key="sk-ant-test",
            system_prompt="sys",
            user_prompt="hi",
            cfg=_cfg(),
        )
    # Single turn: api_response_raw is the serialized response (not wrapped in [])
    assert not result.api_response_raw.startswith("[")


# ---------------------------------------------------------------------------
# call_anthropic — api_response_raw for multi-turn is JSON array
# ---------------------------------------------------------------------------


def test_api_response_raw_multi_turn():
    patcher, client = _patch_anthropic()
    with patcher:
        resp1 = _make_response(
            content=[_make_tool_use_block()],
            stop_reason="tool_use",
        )
        resp2 = _make_response(
            content=[_make_text_block("done")],
            stop_reason="end_turn",
        )
        client.messages.create.side_effect = [resp1, resp2]

        from vsevals.providers.anthropic_provider import call_anthropic

        result = call_anthropic(
            model_id="claude-haiku-4-5",
            api_key="sk-ant-test",
            system_prompt="sys",
            user_prompt="hi",
            cfg=_cfg(),
            tool_schemas=[_tool_schema()],
            tool_handlers={"search_snippets": lambda inp: {"ok": True}},
        )
    # Multi-turn: api_response_raw is wrapped in []
    assert result.api_response_raw.startswith("[")
    assert result.api_response_raw.endswith("]")


# ---------------------------------------------------------------------------
# call_anthropic — max_tokens defaults to 4096
# ---------------------------------------------------------------------------


def test_max_tokens_default():
    patcher, client = _patch_anthropic()
    with patcher:
        client.messages.create.return_value = _make_response()

        from vsevals.providers.anthropic_provider import call_anthropic

        call_anthropic(
            model_id="claude-haiku-4-5",
            api_key="sk-ant-test",
            system_prompt="sys",
            user_prompt="hi",
            cfg=_cfg(),
        )
        kwargs = client.messages.create.call_args.kwargs
    assert kwargs["max_tokens"] == 4096


# ---------------------------------------------------------------------------
# call_anthropic — explicit max_tokens override
# ---------------------------------------------------------------------------


def test_max_tokens_override():
    patcher, client = _patch_anthropic()
    with patcher:
        client.messages.create.return_value = _make_response()

        from vsevals.providers.anthropic_provider import call_anthropic

        call_anthropic(
            model_id="claude-haiku-4-5",
            api_key="sk-ant-test",
            system_prompt="sys",
            user_prompt="hi",
            cfg=_cfg(max_tokens=1024),
        )
        kwargs = client.messages.create.call_args.kwargs
    assert kwargs["max_tokens"] == 1024
