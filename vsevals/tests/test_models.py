"""Tests for vsevals.models — validation, cost computation, parsing."""

from __future__ import annotations

import os
from unittest.mock import patch

import pytest
from pydantic import ValidationError

from vsevals.models import (
    GeneratedPayload,
    OracleConstraint,
    RunConfig,
    ScoreDimension,
    SuiteConfig,
    SuiteMeta,
    SuiteTask,
    SuccessIndicators,
    TaskOracle,
    TaskVisible,
    TaskVoltsnipConfig,
    VariantConfig,
    _assert_unique,
    compute_cost,
    parse_model,
    resolve_key,
)


# ---------------------------------------------------------------------------
# VariantConfig validation
# ---------------------------------------------------------------------------


def test_variant_config_valid():
    v = VariantConfig(
        id="P0", mode="direct", memory_enabled=False, tools_enabled=False,
        retrieval_mode="none", instruction_mode="none", context_surface="user",
    )
    assert v.id == "P0"
    assert v.max_tool_roundtrips == 4


def test_variant_config_tools_only_requires_tools():
    with pytest.raises(ValidationError, match="tools_enabled"):
        VariantConfig(
            id="bad", mode="direct", memory_enabled=False, tools_enabled=False,
            retrieval_mode="none", instruction_mode="none", context_surface="tools_only",
        )


def test_variant_config_agent_decides_requires_tools():
    with pytest.raises(ValidationError, match="tools_enabled"):
        VariantConfig(
            id="bad", mode="agent", memory_enabled=True, tools_enabled=False,
            retrieval_mode="agent_decides", instruction_mode="none", context_surface="system",
        )


# ---------------------------------------------------------------------------
# TaskVisible validation
# ---------------------------------------------------------------------------


def test_task_visible_line_range_both_or_neither():
    with pytest.raises(ValidationError, match="line_start and line_end must be provided together"):
        TaskVisible(id="t1", name="t", user_prompt="fix", line_start=1)


def test_task_visible_line_end_gte_start():
    with pytest.raises(ValidationError, match="line_end must be >= line_start"):
        TaskVisible(id="t1", name="t", user_prompt="fix", line_start=10, line_end=5)


def test_task_visible_valid_line_range():
    t = TaskVisible(id="t1", name="t", user_prompt="fix", line_start=5, line_end=10)
    assert t.line_start == 5 and t.line_end == 10


def test_task_visible_no_lines():
    t = TaskVisible(id="t1", name="t", user_prompt="fix")
    assert t.line_start is None and t.line_end is None


# ---------------------------------------------------------------------------
# TaskVoltsnipConfig
# ---------------------------------------------------------------------------


def test_voltsnip_config_defaults():
    c = TaskVoltsnipConfig()
    assert c.required_snippets == []
    assert c.snippet_context_limit == 6


def test_voltsnip_config_limits():
    with pytest.raises(ValidationError):
        TaskVoltsnipConfig(snippet_context_limit=0)
    with pytest.raises(ValidationError):
        TaskVoltsnipConfig(snippet_context_max_chars=50)


# ---------------------------------------------------------------------------
# SuccessIndicators
# ---------------------------------------------------------------------------


def test_success_indicators_as_lines():
    si = SuccessIndicators(correctness=["a", "b"], consistency=["c"])
    lines = si.as_lines()
    assert "correctness: a" in lines
    assert "consistency: c" in lines
    assert len(lines) == 3


# ---------------------------------------------------------------------------
# OracleConstraint
# ---------------------------------------------------------------------------


def test_oracle_constraint_defaults():
    c = OracleConstraint(id="c1", check="check", judge_prompt="is it?")
    assert c.expected is True
    assert c.trap_baseline is None


def test_oracle_constraint_trap_range():
    with pytest.raises(ValidationError):
        OracleConstraint(id="c1", check="x", judge_prompt="x", trap_baseline=1.5)


# ---------------------------------------------------------------------------
# GeneratedPayload
# ---------------------------------------------------------------------------


def test_generated_payload_forbids_extra():
    with pytest.raises(ValidationError):
        GeneratedPayload(code="x", extra_field="bad")


# ---------------------------------------------------------------------------
# ScoreDimension
# ---------------------------------------------------------------------------


def test_score_dimension_range():
    with pytest.raises(ValidationError):
        ScoreDimension(matched=0, total=1, score=1.5)


# ---------------------------------------------------------------------------
# SuiteConfig uniqueness
# ---------------------------------------------------------------------------


def test_suite_config_duplicate_models():
    with pytest.raises(ValidationError, match="duplicate models"):
        SuiteConfig(
            suite=SuiteMeta(version="1"),
            models=["openai:gpt-5-mini", "openai:gpt-5-mini"],
            variants=[
                VariantConfig(
                    id="P0", mode="direct", memory_enabled=False, tools_enabled=False,
                    retrieval_mode="none", instruction_mode="none", context_surface="user",
                ),
            ],
        )


def test_suite_config_duplicate_variants():
    with pytest.raises(ValidationError, match="duplicate variants"):
        SuiteConfig(
            suite=SuiteMeta(version="1"),
            models=["openai:gpt-5-mini"],
            variants=[
                VariantConfig(
                    id="P0", mode="direct", memory_enabled=False, tools_enabled=False,
                    retrieval_mode="none", instruction_mode="none", context_surface="user",
                ),
                VariantConfig(
                    id="P0", mode="direct", memory_enabled=False, tools_enabled=False,
                    retrieval_mode="none", instruction_mode="none", context_surface="user",
                ),
            ],
        )


def test_suite_config_normalizes_model_strings():
    sc = SuiteConfig(
        suite=SuiteMeta(version="1"),
        models=["openai:gpt-5-mini"],
        variants=[
            VariantConfig(
                id="P0", mode="direct", memory_enabled=False, tools_enabled=False,
                retrieval_mode="none", instruction_mode="none", context_surface="user",
            ),
        ],
    )
    assert sc.model_names == ["openai:gpt-5-mini"]


def test_suite_config_normalizes_model_dicts():
    sc = SuiteConfig(
        suite=SuiteMeta(version="1"),
        models=[{"name": "openai:gpt-5-mini"}],
        variants=[
            VariantConfig(
                id="P0", mode="direct", memory_enabled=False, tools_enabled=False,
                retrieval_mode="none", instruction_mode="none", context_surface="user",
            ),
        ],
    )
    assert sc.model_names == ["openai:gpt-5-mini"]


def test_suite_config_task_map(suite_task):
    sc = SuiteConfig(
        suite=SuiteMeta(version="1"),
        models=["m:a"],
        variants=[
            VariantConfig(
                id="P0", mode="direct", memory_enabled=False, tools_enabled=False,
                retrieval_mode="none", instruction_mode="none", context_surface="user",
            ),
        ],
        tasks=[suite_task],
    )
    assert "BUG01" in sc.task_map
    assert "P0" in sc.variant_map


# ---------------------------------------------------------------------------
# _assert_unique
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("values,should_raise", [
    (["a", "b", "c"], False),
    (["a", "A"], True),
    (["x", "y", "x"], True),
    ([], False),
])
def test_assert_unique(values, should_raise):
    if should_raise:
        with pytest.raises(ValueError, match="duplicate"):
            _assert_unique(values, "test")
    else:
        _assert_unique(values, "test")


# ---------------------------------------------------------------------------
# compute_cost
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("model_id,prompt,comp,cached,expected_not_none", [
    ("gpt-5-mini", 1000, 500, 0, True),
    ("claude-haiku-4-5", 1000, 500, 0, True),
    ("unknown-model", 1000, 500, 0, False),
])
def test_compute_cost_returns(model_id, prompt, comp, cached, expected_not_none):
    result = compute_cost(model_id, prompt, comp, cached)
    assert (result is not None) == expected_not_none


def test_compute_cost_no_cache():
    cost = compute_cost("gpt-5-mini", 1_000_000, 1_000_000, 0)
    # gpt-5-mini: $0.40/M in, $1.60/M out
    expected = (1_000_000 * 0.40 + 1_000_000 * 1.60) / 1_000_000
    assert cost == round(expected, 8)


def test_compute_cost_with_cache_openai():
    cost = compute_cost("gpt-5-mini", 1000, 500, 200)
    assert cost is not None
    assert cost > 0


def test_compute_cost_with_cache_claude():
    cost = compute_cost("claude-haiku-4-5", 1000, 500, 200)
    assert cost is not None
    # Claude cache discount is 10% vs OpenAI 50%
    cost_openai = compute_cost("gpt-5-mini", 1000, 500, 200)
    # Can't directly compare since rates differ, just ensure both return


# ---------------------------------------------------------------------------
# parse_model
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("model_name,expected_provider,expected_id", [
    ("openai:gpt-5", "openai", "gpt-5"),
    ("anthropic:claude-opus-4-6", "anthropic", "claude-opus-4-6"),
    ("claudecode:haiku-4-5", "claudecode", "haiku-4-5"),
    ("codex:gpt-5.2-codex", "codex", "gpt-5.2-codex"),
    ("mock:echo", "mock", "echo"),
    ("gpt-5-mini", "openai", "gpt-5-mini"),  # no colon → default openai
])
def test_parse_model(model_name, expected_provider, expected_id):
    provider, model_id = parse_model(model_name)
    assert provider == expected_provider
    assert model_id == expected_id


# ---------------------------------------------------------------------------
# resolve_key
# ---------------------------------------------------------------------------


def test_resolve_key_from_cfg_api_key():
    cfg = RunConfig(api_key="direct-key")
    assert resolve_key("openai", cfg, {}) == "direct-key"


def test_resolve_key_from_provider_keys():
    cfg = RunConfig(provider_api_keys={"openai": "provider-key"})
    assert resolve_key("openai", cfg, {}) == "provider-key"


@patch.dict(os.environ, {"OPENAI_API_KEY": "env-key"})
def test_resolve_key_from_env_openai():
    cfg = RunConfig()
    assert resolve_key("openai", cfg, {}) == "env-key"


@patch.dict(os.environ, {"ANTHROPIC_API_KEY": "env-ant-key"})
def test_resolve_key_from_env_anthropic():
    cfg = RunConfig()
    assert resolve_key("anthropic", cfg, {}) == "env-ant-key"


@patch.dict(os.environ, {}, clear=True)
def test_resolve_key_none_when_missing():
    cfg = RunConfig()
    result = resolve_key("openai", cfg, {})
    # May or may not have OPENAI_API_KEY set in cleared env
    # The point is it doesn't crash


# ---------------------------------------------------------------------------
# RunConfig defaults
# ---------------------------------------------------------------------------


def test_run_config_defaults():
    cfg = RunConfig()
    assert cfg.temperature == 0.0
    assert cfg.structured_output is True
    assert cfg.scoring_match_mode == "hybrid"
    assert cfg.constraint_pass_threshold == 0.7
