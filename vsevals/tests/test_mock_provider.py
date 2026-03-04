"""Tests for vsevals.providers.mock — mock LLM provider."""

from __future__ import annotations

import json

import pytest

from vsevals.models import RunConfig
from vsevals.providers.mock import call_mock


# ---------------------------------------------------------------------------
# call_mock — default mode
# ---------------------------------------------------------------------------


def test_call_mock_default():
    cfg = RunConfig(structured_output=True)
    result = call_mock(model_id="default", system_prompt="sys", user_prompt="test", cfg=cfg)
    assert result.raw_output
    parsed = json.loads(result.raw_output)
    assert parsed["code"] == "def mock(): pass"
    assert result.token_usage.prompt_tokens == 10
    assert result.token_usage.completion_tokens == 20
    assert result.finish_reason == "stop"
    assert result.request_id == "mock-123"


# ---------------------------------------------------------------------------
# call_mock — echo mode
# ---------------------------------------------------------------------------


def test_call_mock_echo():
    cfg = RunConfig(structured_output=True)
    result = call_mock(model_id="echo", system_prompt="sys", user_prompt="hello world", cfg=cfg)
    parsed = json.loads(result.raw_output)
    assert parsed["code"] == "hello world"


def test_call_mock_echo_unstructured():
    cfg = RunConfig(structured_output=False)
    result = call_mock(model_id="echo", system_prompt="sys", user_prompt="raw text", cfg=cfg)
    assert result.raw_output == "raw text"
    assert result.parsed_output.code == "raw text"


# ---------------------------------------------------------------------------
# call_mock — structured output tracking
# ---------------------------------------------------------------------------


def test_call_mock_structured_output_succeeded():
    cfg = RunConfig(structured_output=True)
    result = call_mock(model_id="default", system_prompt="sys", user_prompt="test", cfg=cfg)
    assert result.structured_output_attempted is True
    assert result.structured_output_succeeded is True


def test_call_mock_unstructured():
    cfg = RunConfig(structured_output=False)
    result = call_mock(model_id="default", system_prompt="sys", user_prompt="test", cfg=cfg)
    assert result.structured_output_attempted is False
    assert result.structured_output_succeeded is False


# ---------------------------------------------------------------------------
# call_mock — timing
# ---------------------------------------------------------------------------


def test_call_mock_timing():
    cfg = RunConfig()
    result = call_mock(model_id="default", system_prompt="sys", user_prompt="test", cfg=cfg)
    assert result.request_started_at is not None
    assert result.request_finished_at is not None
    assert result.request_latency_ms is not None
    assert result.request_latency_ms >= 0
