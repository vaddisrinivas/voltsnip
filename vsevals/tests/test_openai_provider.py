"""Tests for vsevals.providers.openai — OpenAI Chat, Responses+MCP, and router."""

from __future__ import annotations

import sys
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from vsevals.models import RunConfig, LLMResult


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_usage(
    prompt_tokens=10,
    completion_tokens=20,
    cached_tokens=0,
    reasoning_tokens=None,
):
    """Build a mock usage object matching the OpenAI SDK shape."""
    prompt_details = SimpleNamespace(cached_tokens=cached_tokens)
    ct_details = SimpleNamespace(reasoning_tokens=reasoning_tokens) if reasoning_tokens is not None else None
    return SimpleNamespace(
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        prompt_tokens_details=prompt_details,
        completion_tokens_details=ct_details,
    )


def _make_chat_response(
    content="hello",
    finish_reason="stop",
    usage=None,
    request_id="req-1",
):
    """Build a mock ChatCompletion-style response."""
    msg = SimpleNamespace(content=content)
    choice = SimpleNamespace(finish_reason=finish_reason, message=msg)
    resp = MagicMock()
    resp.id = request_id
    resp.choices = [choice]
    resp.usage = usage or _make_usage()
    resp.model_dump_json.return_value = '{"id":"req-1"}'
    return resp


def _make_responses_response(output_text="done", usage=None, request_id="resp-1"):
    """Build a mock Responses API response."""
    u = usage or SimpleNamespace(
        input_tokens=5,
        output_tokens=15,
        input_tokens_details=SimpleNamespace(cached_tokens=0),
        output_tokens_details=SimpleNamespace(reasoning_tokens=None),
    )
    resp = MagicMock()
    resp.output_text = output_text
    resp.usage = u
    resp.id = request_id
    resp.model_dump_json.return_value = '{"id":"resp-1"}'
    return resp


def _cfg(**overrides) -> RunConfig:
    defaults = dict(
        api_key="sk-test",
        structured_output=False,
        voltsnip_base_url="https://api.example.com",
    )
    defaults.update(overrides)
    return RunConfig(**defaults)


def _patch_openai():
    """Return a patch context that injects a mock OpenAI class into the openai module."""
    mock_openai_module = MagicMock()
    mock_client = MagicMock()
    mock_openai_module.OpenAI.return_value = mock_client
    return patch.dict(sys.modules, {"openai": mock_openai_module}), mock_client


# ---------------------------------------------------------------------------
# call_openai_chat — basic call
# ---------------------------------------------------------------------------


def test_chat_basic_call():
    patcher, client = _patch_openai()
    with patcher:
        client.chat.completions.create.return_value = _make_chat_response(content="result text")

        # Re-import to pick up the mocked module
        from vsevals.providers.openai import call_openai_chat

        result = call_openai_chat(
            model_id="gpt-5-mini",
            api_key="sk-test",
            system_prompt="You are helpful.",
            user_prompt="Say hello.",
            cfg=_cfg(),
        )
    assert isinstance(result, LLMResult)
    assert result.raw_output == "result text"
    assert result.finish_reason == "stop"
    assert result.request_id == "req-1"


# ---------------------------------------------------------------------------
# call_openai_chat — temperature
# ---------------------------------------------------------------------------


def test_chat_with_temperature():
    patcher, client = _patch_openai()
    with patcher:
        client.chat.completions.create.return_value = _make_chat_response()

        from vsevals.providers.openai import call_openai_chat

        call_openai_chat(
            model_id="gpt-5-mini",
            api_key="sk-test",
            system_prompt="sys",
            user_prompt="hi",
            cfg=_cfg(temperature=0.7),
        )
        kwargs = client.chat.completions.create.call_args.kwargs
    assert kwargs["temperature"] == 0.7


# ---------------------------------------------------------------------------
# call_openai_chat — structured_output
# ---------------------------------------------------------------------------


def test_chat_structured_output():
    patcher, client = _patch_openai()
    with patcher:
        client.chat.completions.create.return_value = _make_chat_response(
            content='{"code":"x","comments":""}',
        )

        from vsevals.providers.openai import call_openai_chat

        result = call_openai_chat(
            model_id="gpt-5-mini",
            api_key="sk-test",
            system_prompt="You are helpful.",
            user_prompt="Do it.",
            cfg=_cfg(structured_output=True),
        )
        kwargs = client.chat.completions.create.call_args.kwargs
    system_msg = kwargs["messages"][0]["content"]
    assert system_msg.endswith("\n\nYou must output valid JSON.")
    assert kwargs["response_format"] == {"type": "json_object"}
    assert result.structured_output_attempted is True


# ---------------------------------------------------------------------------
# call_openai_chat — max_tokens
# ---------------------------------------------------------------------------


def test_chat_max_tokens():
    patcher, client = _patch_openai()
    with patcher:
        client.chat.completions.create.return_value = _make_chat_response()

        from vsevals.providers.openai import call_openai_chat

        call_openai_chat(
            model_id="gpt-5-mini",
            api_key="sk-test",
            system_prompt="sys",
            user_prompt="hi",
            cfg=_cfg(max_tokens=512),
        )
        kwargs = client.chat.completions.create.call_args.kwargs
    assert kwargs["max_completion_tokens"] == 512


# ---------------------------------------------------------------------------
# call_openai_chat — reasoning_effort
# ---------------------------------------------------------------------------


def test_chat_reasoning_effort():
    patcher, client = _patch_openai()
    with patcher:
        client.chat.completions.create.return_value = _make_chat_response()

        from vsevals.providers.openai import call_openai_chat

        call_openai_chat(
            model_id="o3",
            api_key="sk-test",
            system_prompt="sys",
            user_prompt="hi",
            cfg=_cfg(reasoning_effort="high"),
        )
        kwargs = client.chat.completions.create.call_args.kwargs
    assert kwargs["reasoning_effort"] == "high"


# ---------------------------------------------------------------------------
# call_openai_chat — temperature retry succeeds
# ---------------------------------------------------------------------------


def test_chat_temperature_retry_succeeds():
    patcher, client = _patch_openai()
    with patcher:
        client.chat.completions.create.side_effect = [
            Exception("temperature not supported for this model"),
            _make_chat_response(content="retry ok"),
        ]

        from vsevals.providers.openai import call_openai_chat

        result = call_openai_chat(
            model_id="o3",
            api_key="sk-test",
            system_prompt="sys",
            user_prompt="hi",
            cfg=_cfg(temperature=0.5),
        )
    assert result.raw_output == "retry ok"
    # Second call should NOT have temperature
    retry_kwargs = client.chat.completions.create.call_args_list[1].kwargs
    assert "temperature" not in retry_kwargs


# ---------------------------------------------------------------------------
# call_openai_chat — temperature retry fails
# ---------------------------------------------------------------------------


def test_chat_temperature_retry_fails():
    patcher, client = _patch_openai()
    with patcher:
        client.chat.completions.create.side_effect = [
            Exception("temperature not supported"),
            Exception("still broken"),
        ]

        from vsevals.providers.openai import call_openai_chat

        with pytest.raises(RuntimeError, match="openai call failed"):
            call_openai_chat(
                model_id="o3",
                api_key="sk-test",
                system_prompt="sys",
                user_prompt="hi",
                cfg=_cfg(temperature=0.5),
            )


# ---------------------------------------------------------------------------
# call_openai_chat — non-temperature error
# ---------------------------------------------------------------------------


def test_chat_non_temperature_error():
    patcher, client = _patch_openai()
    with patcher:
        client.chat.completions.create.side_effect = Exception("rate limit exceeded")

        from vsevals.providers.openai import call_openai_chat

        with pytest.raises(RuntimeError, match="openai call failed"):
            call_openai_chat(
                model_id="gpt-5-mini",
                api_key="sk-test",
                system_prompt="sys",
                user_prompt="hi",
                cfg=_cfg(),
            )


# ---------------------------------------------------------------------------
# call_openai_chat — usage extraction
# ---------------------------------------------------------------------------


def test_chat_usage_extraction():
    patcher, client = _patch_openai()
    with patcher:
        usage = _make_usage(prompt_tokens=100, completion_tokens=50, cached_tokens=10)
        client.chat.completions.create.return_value = _make_chat_response(usage=usage)

        from vsevals.providers.openai import call_openai_chat

        result = call_openai_chat(
            model_id="gpt-5-mini",
            api_key="sk-test",
            system_prompt="sys",
            user_prompt="hi",
            cfg=_cfg(),
        )
    assert result.token_usage.prompt_tokens == 100
    assert result.token_usage.completion_tokens == 50
    assert result.token_usage.cached_tokens == 10
    assert result.token_usage.total_tokens == 150


# ---------------------------------------------------------------------------
# call_openai_chat — thinking_tokens from reasoning_tokens
# ---------------------------------------------------------------------------


def test_chat_thinking_tokens():
    patcher, client = _patch_openai()
    with patcher:
        usage = _make_usage(reasoning_tokens=42)
        client.chat.completions.create.return_value = _make_chat_response(usage=usage)

        from vsevals.providers.openai import call_openai_chat

        result = call_openai_chat(
            model_id="o3",
            api_key="sk-test",
            system_prompt="sys",
            user_prompt="hi",
            cfg=_cfg(),
        )
    assert result.token_usage.thinking_tokens == 42


# ---------------------------------------------------------------------------
# call_openai_chat — content as list
# ---------------------------------------------------------------------------


def test_chat_content_as_list():
    patcher, client = _patch_openai()
    with patcher:
        content_list = [{"text": "part1"}, {"text": "part2"}]
        client.chat.completions.create.return_value = _make_chat_response(content=content_list)

        from vsevals.providers.openai import call_openai_chat

        result = call_openai_chat(
            model_id="gpt-5-mini",
            api_key="sk-test",
            system_prompt="sys",
            user_prompt="hi",
            cfg=_cfg(),
        )
    assert result.raw_output == "part1\npart2"


# ---------------------------------------------------------------------------
# call_openai_chat — missing usage (None)
# ---------------------------------------------------------------------------


def test_chat_missing_usage():
    patcher, client = _patch_openai()
    with patcher:
        resp = _make_chat_response()
        resp.usage = None
        client.chat.completions.create.return_value = resp

        from vsevals.providers.openai import call_openai_chat

        result = call_openai_chat(
            model_id="gpt-5-mini",
            api_key="sk-test",
            system_prompt="sys",
            user_prompt="hi",
            cfg=_cfg(),
        )
    assert result.token_usage.prompt_tokens == 0
    assert result.token_usage.completion_tokens == 0
    assert result.token_usage.cached_tokens == 0
    assert result.token_usage.thinking_tokens is None


# ---------------------------------------------------------------------------
# call_openai_chat — content as string (explicit)
# ---------------------------------------------------------------------------


def test_chat_content_string():
    patcher, client = _patch_openai()
    with patcher:
        client.chat.completions.create.return_value = _make_chat_response(content="plain string")

        from vsevals.providers.openai import call_openai_chat

        result = call_openai_chat(
            model_id="gpt-5-mini",
            api_key="sk-test",
            system_prompt="sys",
            user_prompt="hi",
            cfg=_cfg(),
        )
    assert result.raw_output == "plain string"


# ---------------------------------------------------------------------------
# call_openai_with_mcp — localhost raises RuntimeError
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("base_url", [
    "http://localhost:8000",
    "http://127.0.0.1:8000",
    "http://0.0.0.0:9999",
])
def test_mcp_localhost_raises(base_url):
    patcher, client = _patch_openai()
    with patcher:
        from vsevals.providers.openai import call_openai_with_mcp

        with pytest.raises(RuntimeError, match="publicly accessible server"):
            call_openai_with_mcp(
                model_id="gpt-5-mini",
                api_key="sk-test",
                system_prompt="sys",
                user_prompt="hi",
                cfg=_cfg(voltsnip_base_url=base_url),
            )


# ---------------------------------------------------------------------------
# call_openai_with_mcp — success with public URL
# ---------------------------------------------------------------------------


def test_mcp_public_url_success():
    patcher, client = _patch_openai()
    with patcher:
        client.responses.create.return_value = _make_responses_response(output_text="mcp result")

        from vsevals.providers.openai import call_openai_with_mcp

        result = call_openai_with_mcp(
            model_id="gpt-5-mini",
            api_key="sk-test",
            system_prompt="sys",
            user_prompt="hi",
            cfg=_cfg(voltsnip_base_url="https://api.example.com"),
        )
    assert isinstance(result, LLMResult)
    assert result.raw_output == "mcp result"
    assert result.finish_reason == "stop"


# ---------------------------------------------------------------------------
# call_openai_with_mcp — max_tokens maps to max_output_tokens
# ---------------------------------------------------------------------------


def test_mcp_max_tokens():
    patcher, client = _patch_openai()
    with patcher:
        client.responses.create.return_value = _make_responses_response()

        from vsevals.providers.openai import call_openai_with_mcp

        call_openai_with_mcp(
            model_id="gpt-5-mini",
            api_key="sk-test",
            system_prompt="sys",
            user_prompt="hi",
            cfg=_cfg(voltsnip_base_url="https://api.example.com", max_tokens=256),
        )
        kwargs = client.responses.create.call_args.kwargs
    assert kwargs["max_output_tokens"] == 256


# ---------------------------------------------------------------------------
# call_openai_with_mcp — API error
# ---------------------------------------------------------------------------


def test_mcp_api_error():
    patcher, client = _patch_openai()
    with patcher:
        client.responses.create.side_effect = Exception("server error")

        from vsevals.providers.openai import call_openai_with_mcp

        with pytest.raises(RuntimeError, match="openai responses API call failed"):
            call_openai_with_mcp(
                model_id="gpt-5-mini",
                api_key="sk-test",
                system_prompt="sys",
                user_prompt="hi",
                cfg=_cfg(voltsnip_base_url="https://api.example.com"),
            )


# ---------------------------------------------------------------------------
# call_openai — router without tool_schemas (goes to chat)
# ---------------------------------------------------------------------------


@patch("vsevals.providers.openai.call_openai_chat")
def test_router_without_tools(mock_chat):
    mock_chat.return_value = MagicMock(spec=LLMResult)

    from vsevals.providers.openai import call_openai

    result = call_openai(
        model_id="gpt-5-mini",
        api_key="sk-test",
        system_prompt="sys",
        user_prompt="hi",
        cfg=_cfg(),
    )
    mock_chat.assert_called_once()
    assert result is mock_chat.return_value


# ---------------------------------------------------------------------------
# call_openai — router with tool_schemas (goes to MCP)
# ---------------------------------------------------------------------------


@patch("vsevals.providers.openai.call_openai_with_mcp")
def test_router_with_tools(mock_mcp):
    mock_mcp.return_value = MagicMock(spec=LLMResult)

    from vsevals.providers.openai import call_openai

    result = call_openai(
        model_id="gpt-5-mini",
        api_key="sk-test",
        system_prompt="sys",
        user_prompt="hi",
        cfg=_cfg(),
        tool_schemas=[{"function": {"name": "search"}}],
    )
    mock_mcp.assert_called_once()
    assert result is mock_mcp.return_value


# ---------------------------------------------------------------------------
# call_openai_chat — temperature 0.0 is passed (not None)
# ---------------------------------------------------------------------------


def test_chat_temperature_zero_is_passed():
    patcher, client = _patch_openai()
    with patcher:
        client.chat.completions.create.return_value = _make_chat_response()

        from vsevals.providers.openai import call_openai_chat

        call_openai_chat(
            model_id="gpt-5-mini",
            api_key="sk-test",
            system_prompt="sys",
            user_prompt="hi",
            cfg=_cfg(temperature=0.0),
        )
        kwargs = client.chat.completions.create.call_args.kwargs
    assert kwargs["temperature"] == 0.0


# ---------------------------------------------------------------------------
# call_openai_with_mcp — default base_url is localhost (raises)
# ---------------------------------------------------------------------------


def test_mcp_default_base_url_raises():
    patcher, client = _patch_openai()
    with patcher:
        from vsevals.providers.openai import call_openai_with_mcp

        cfg = RunConfig(api_key="sk-test", structured_output=False, voltsnip_base_url=None)
        with pytest.raises(RuntimeError, match="publicly accessible server"):
            call_openai_with_mcp(
                model_id="gpt-5-mini",
                api_key="sk-test",
                system_prompt="sys",
                user_prompt="hi",
                cfg=cfg,
            )
