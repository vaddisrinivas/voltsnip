"""Tests for vsevals.dispatch — provider routing and tool schemas."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from vsevals.dispatch import (
    call_judge,
    call_llm,
    filesystem_tool_schemas,
    harness_tool_schemas,
    voltsnip_tool_schemas,
)
from vsevals.models import RunConfig


# ---------------------------------------------------------------------------
# harness_tool_schemas
# ---------------------------------------------------------------------------


def test_harness_tool_schemas_structure():
    schemas = harness_tool_schemas()
    assert len(schemas) == 5
    names = [s["function"]["name"] for s in schemas]
    assert "read_file" in names
    assert "glob_files" in names
    assert "grep_files" in names
    assert "search_memory" in names
    assert "get_snippet_by_canonical_key" in names


def test_harness_tool_schemas_valid_json_schema():
    for schema in harness_tool_schemas():
        assert schema["type"] == "function"
        func = schema["function"]
        assert "name" in func
        assert "description" in func
        assert "parameters" in func
        assert func["parameters"]["type"] == "object"


def test_filesystem_tool_schemas():
    fs = filesystem_tool_schemas()
    assert len(fs) == 3
    names = [s["function"]["name"] for s in fs]
    assert set(names) == {"read_file", "glob_files", "grep_files"}


def test_voltsnip_tool_schemas():
    vs = voltsnip_tool_schemas()
    assert len(vs) == 2
    names = [s["function"]["name"] for s in vs]
    assert "search_memory" in names
    assert "get_snippet_by_canonical_key" in names


# ---------------------------------------------------------------------------
# call_llm — provider dispatch
# ---------------------------------------------------------------------------


@patch("vsevals.dispatch.parse_model", return_value=("mock", "default"))
@patch("vsevals.providers.mock.call_mock")
def test_call_llm_mock(mock_call, mock_parse):
    cfg = RunConfig()
    mock_call.return_value = MagicMock()
    call_llm(
        model_name="mock:default",
        system_prompt="sys",
        user_prompt="usr",
        cfg=cfg,
        provider_keys={},
    )
    mock_call.assert_called_once()


def test_call_llm_unsupported_provider():
    cfg = RunConfig()
    with pytest.raises(ValueError, match="unsupported provider"):
        call_llm(
            model_name="unsupported:model",
            system_prompt="sys",
            user_prompt="usr",
            cfg=cfg,
            provider_keys={},
        )


# ---------------------------------------------------------------------------
# call_judge — provider dispatch
# ---------------------------------------------------------------------------


@patch("vsevals.dispatch.parse_model", return_value=("mock", "default"))
@patch("vsevals.providers.mock.call_mock")
def test_call_judge_mock(mock_call, mock_parse):
    cfg = RunConfig()
    mock_result = MagicMock()
    mock_result.raw_output = '{"results": [true]}'
    mock_call.return_value = mock_result
    result = call_judge(
        model_name="mock:default",
        system_prompt="judge",
        user_prompt="evaluate",
        cfg=cfg,
        provider_keys={},
    )
    assert result == '{"results": [true]}'


def test_call_judge_unsupported_provider():
    cfg = RunConfig()
    with pytest.raises(ValueError, match="unsupported judge provider"):
        call_judge(
            model_name="unsupported:model",
            system_prompt="judge",
            user_prompt="evaluate",
            cfg=cfg,
            provider_keys={},
        )


# ---------------------------------------------------------------------------
# call_llm — anthropic dispatch
# ---------------------------------------------------------------------------


@patch("vsevals.providers.anthropic_provider.call_anthropic")
def test_call_llm_anthropic(mock_call):
    cfg = RunConfig()
    mock_call.return_value = MagicMock()
    call_llm(
        model_name="anthropic:claude-haiku-4-5",
        system_prompt="sys",
        user_prompt="usr",
        cfg=cfg,
        provider_keys={"anthropic": "test-key"},
    )
    mock_call.assert_called_once()
    assert mock_call.call_args.kwargs["api_key"] == "test-key"


# ---------------------------------------------------------------------------
# call_llm — openai dispatch
# ---------------------------------------------------------------------------


@patch("vsevals.providers.openai.call_openai")
def test_call_llm_openai(mock_call):
    cfg = RunConfig()
    mock_call.return_value = MagicMock()
    call_llm(
        model_name="openai:gpt-5-mini",
        system_prompt="sys",
        user_prompt="usr",
        cfg=cfg,
        provider_keys={"openai": "test-key"},
    )
    mock_call.assert_called_once()


# ---------------------------------------------------------------------------
# call_llm — claudecode dispatch
# ---------------------------------------------------------------------------


@patch("vsevals.providers.claudecode.call_claudecode")
def test_call_llm_claudecode(mock_call):
    cfg = RunConfig()
    mock_call.return_value = MagicMock()
    call_llm(
        model_name="claudecode:haiku-4-5",
        system_prompt="sys",
        user_prompt="usr",
        cfg=cfg,
        provider_keys={},
    )
    mock_call.assert_called_once()
    kw = mock_call.call_args.kwargs
    assert kw["model_id"] == "haiku-4-5"
    assert kw["system_prompt"] == "sys"
    assert kw["user_prompt"] == "usr"


# ---------------------------------------------------------------------------
# call_llm — codex dispatch
# ---------------------------------------------------------------------------


@patch("vsevals.providers.codex.call_codex")
def test_call_llm_codex(mock_call):
    cfg = RunConfig()
    mock_call.return_value = MagicMock()
    call_llm(
        model_name="codex:o3-mini",
        system_prompt="sys",
        user_prompt="usr",
        cfg=cfg,
        provider_keys={},
    )
    mock_call.assert_called_once()
    kw = mock_call.call_args.kwargs
    assert kw["model_id"] == "o3-mini"
    assert kw["system_prompt"] == "sys"


# ---------------------------------------------------------------------------
# call_judge — claudecode dispatch
# ---------------------------------------------------------------------------


@patch("vsevals.providers.claudecode.call_claudecode")
def test_call_judge_claudecode(mock_call):
    cfg = RunConfig()
    mock_result = MagicMock()
    mock_result.raw_output = "judge claudecode output"
    mock_call.return_value = mock_result
    result = call_judge(
        model_name="claudecode:haiku-4-5",
        system_prompt="judge sys",
        user_prompt="evaluate",
        cfg=cfg,
        provider_keys={},
    )
    assert result == "judge claudecode output"
    mock_call.assert_called_once()


# ---------------------------------------------------------------------------
# call_judge — codex dispatch
# ---------------------------------------------------------------------------


@patch("vsevals.providers.codex.call_codex")
def test_call_judge_codex(mock_call):
    cfg = RunConfig()
    mock_result = MagicMock()
    mock_result.raw_output = "judge codex output"
    mock_call.return_value = mock_result
    result = call_judge(
        model_name="codex:o3-mini",
        system_prompt="judge sys",
        user_prompt="evaluate",
        cfg=cfg,
        provider_keys={},
    )
    assert result == "judge codex output"
    mock_call.assert_called_once()


# ---------------------------------------------------------------------------
# call_judge — anthropic dispatch
# ---------------------------------------------------------------------------


@patch("vsevals.providers.anthropic_provider.call_anthropic")
def test_call_judge_anthropic(mock_call):
    cfg = RunConfig()
    mock_result = MagicMock()
    mock_result.raw_output = "judge anthropic output"
    mock_call.return_value = mock_result
    result = call_judge(
        model_name="anthropic:claude-opus-4-6",
        system_prompt="judge sys",
        user_prompt="evaluate",
        cfg=cfg,
        provider_keys={"anthropic": "test-key"},
    )
    assert result == "judge anthropic output"
    mock_call.assert_called_once()
    kw = mock_call.call_args.kwargs
    assert kw["api_key"] == "test-key"
    assert kw["tool_schemas"] is None


# ---------------------------------------------------------------------------
# call_judge — openai dispatch (uses call_openai_chat)
# ---------------------------------------------------------------------------


@patch("vsevals.providers.openai.call_openai_chat")
def test_call_judge_openai(mock_call):
    cfg = RunConfig()
    mock_result = MagicMock()
    mock_result.raw_output = "judge openai output"
    mock_call.return_value = mock_result
    result = call_judge(
        model_name="openai:gpt-5-mini",
        system_prompt="judge sys",
        user_prompt="evaluate",
        cfg=cfg,
        provider_keys={"openai": "test-key"},
    )
    assert result == "judge openai output"
    mock_call.assert_called_once()
    kw = mock_call.call_args.kwargs
    assert kw["api_key"] == "test-key"


# ---------------------------------------------------------------------------
# call_judge — verifies cfg overrides
# ---------------------------------------------------------------------------


@patch("vsevals.providers.mock.call_mock")
def test_call_judge_sets_no_structured_output(mock_call):
    """Judge must set structured_output=False and temperature=None."""
    cfg = RunConfig(structured_output=True, temperature=0.5)
    mock_result = MagicMock()
    mock_result.raw_output = "result"
    mock_call.return_value = mock_result
    call_judge(
        model_name="mock:default",
        system_prompt="judge",
        user_prompt="evaluate",
        cfg=cfg,
        provider_keys={},
    )
    judge_cfg = mock_call.call_args.kwargs["cfg"]
    assert judge_cfg.structured_output is False
    assert judge_cfg.temperature is None
    # Original cfg should be unmodified
    assert cfg.structured_output is True
    assert cfg.temperature == 0.5
