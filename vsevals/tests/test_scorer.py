"""Tests for vsevals.scorer — scoring logic, JSON parsing, verdict merging."""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest

from vsevals.models import (
    OracleConstraint,
    RunConfig,
    SuccessIndicators,
    TaskOracle,
)
from vsevals.scorer import (
    _coerce_bool_list,
    _coerce_verdict_list,
    _merge_constraint_verdicts,
    _merge_requirement_verdicts,
    _parse_ensemble,
    _parse_json,
    _select_constraints,
    _synthetic_constraints,
    score_one,
)


# ---------------------------------------------------------------------------
# _parse_ensemble
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("spec,expected", [
    ("openai:gpt-5-mini", ["openai:gpt-5-mini"]),
    ("openai:gpt-5+anthropic:claude-opus-4-6", ["openai:gpt-5", "anthropic:claude-opus-4-6"]),
    ("  a + b + c  ", ["a", "b", "c"]),
    ("", []),
])
def test_parse_ensemble(spec, expected):
    assert _parse_ensemble(spec) == expected


# ---------------------------------------------------------------------------
# _parse_json
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("text,expected_key", [
    ('{"results": [true]}', "results"),
    ('some preamble {"results": [false]} trailing', "results"),
    ('{"nested": {"a": 1}}', "nested"),
    ("not json at all", None),
    ("", None),
    ("{invalid json}", None),
])
def test_parse_json(text, expected_key):
    result = _parse_json(text)
    if expected_key is None:
        assert result is None
    else:
        assert expected_key in result


def test_parse_json_embedded_in_text():
    text = 'Here is my response: {"results": [{"verdict": true, "reason": "ok"}]} End.'
    result = _parse_json(text)
    assert result is not None
    assert "results" in result


def test_parse_json_handles_escaped_strings():
    text = '{"code": "line \\"quoted\\"", "comments": ""}'
    result = _parse_json(text)
    assert result is not None
    assert "code" in result


# ---------------------------------------------------------------------------
# _coerce_bool_list
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("raw,length,expected", [
    ([True, False, True], 3, [True, False, True]),
    ([1, 0, 1], 3, [True, False, True]),
    ([True], 3, [True, False, False]),  # padded
    ([True, True, True, True], 2, [True, True]),  # truncated
    ("not a list", 2, None),
    (None, 2, None),
    ([], 2, [False, False]),
])
def test_coerce_bool_list(raw, length, expected):
    assert _coerce_bool_list(raw, length) == expected


# ---------------------------------------------------------------------------
# _coerce_verdict_list
# ---------------------------------------------------------------------------


def test_coerce_verdict_list_rich_format():
    raw = [{"verdict": True, "reason": "good"}, {"verdict": False, "reason": "bad"}]
    result = _coerce_verdict_list(raw, 2)
    assert result[0]["verdict"] is True
    assert result[0]["reason"] == "good"
    assert result[1]["verdict"] is False


def test_coerce_verdict_list_bare_booleans():
    raw = [True, False]
    result = _coerce_verdict_list(raw, 2)
    assert result[0]["verdict"] is True
    assert result[0]["reason"] is None


def test_coerce_verdict_list_padding():
    raw = [{"verdict": True, "reason": "ok"}]
    result = _coerce_verdict_list(raw, 3)
    assert len(result) == 3
    assert result[2]["verdict"] is False


def test_coerce_verdict_list_not_list():
    assert _coerce_verdict_list("not a list", 2) is None


# ---------------------------------------------------------------------------
# _merge_constraint_verdicts
# ---------------------------------------------------------------------------


def test_merge_constraint_verdicts_lenient():
    constraints = [
        OracleConstraint(id="c1", check="x", judge_prompt="x", expected=True),
    ]
    v1 = [{"verdict": True, "reason": "j1"}]
    v2 = [{"verdict": False, "reason": "j2"}]
    result = _merge_constraint_verdicts([v1, v2], constraints)
    assert result[0]["verdict"] is True  # LENIENT: any True → True


def test_merge_constraint_verdicts_strict():
    constraints = [
        OracleConstraint(id="c1", check="x", judge_prompt="x", expected=False),
    ]
    v1 = [{"verdict": True, "reason": "j1"}]
    v2 = [{"verdict": False, "reason": "j2"}]
    result = _merge_constraint_verdicts([v1, v2], constraints)
    assert result[0]["verdict"] is False  # STRICT: all True → True (not all)


def test_merge_constraint_verdicts_empty():
    constraints = [OracleConstraint(id="c1", check="x", judge_prompt="x")]
    result = _merge_constraint_verdicts([], constraints)
    assert result[0]["verdict"] is False


# ---------------------------------------------------------------------------
# _merge_requirement_verdicts
# ---------------------------------------------------------------------------


def test_merge_requirement_verdicts_single():
    single = {"hidden": [True, False], "success": [True], "failure_modes": [False], "evaluation_criteria": None}
    result = _merge_requirement_verdicts([single], {"hidden": 2, "success": 1, "failure_modes": 1, "evaluation_criteria": 0})
    assert result == single


def test_merge_requirement_verdicts_lenient_hidden():
    r1 = {"hidden": [True, False], "failure_modes": [True]}
    r2 = {"hidden": [False, True], "failure_modes": [False]}
    lengths = {"hidden": 2, "failure_modes": 1}
    result = _merge_requirement_verdicts([r1, r2], lengths)
    assert result["hidden"] == [True, True]  # LENIENT
    assert result["failure_modes"] == [False]  # STRICT: not all True


def test_merge_requirement_verdicts_empty():
    result = _merge_requirement_verdicts([], {"hidden": 2})
    assert result["hidden"] is None


# ---------------------------------------------------------------------------
# _select_constraints
# ---------------------------------------------------------------------------


def test_select_constraints_explicit():
    oracle = TaskOracle(constraints=[
        OracleConstraint(id="c1", check="x", judge_prompt="x"),
    ])
    cfg = RunConfig(auto_constraints_from_legacy_oracle=True)
    result = _select_constraints(oracle, "auto", cfg)
    assert len(result) == 1


def test_select_constraints_legacy_weighted_forces_empty():
    oracle = TaskOracle(constraints=[
        OracleConstraint(id="c1", check="x", judge_prompt="x"),
    ])
    cfg = RunConfig()
    result = _select_constraints(oracle, "legacy_weighted", cfg)
    assert result == []


def test_select_constraints_auto_synthesizes():
    oracle = TaskOracle(
        hidden_requirements=["req1", "req2"],
        failure_modes=["fail1"],
    )
    cfg = RunConfig(auto_constraints_from_legacy_oracle=True)
    result = _select_constraints(oracle, "auto", cfg)
    assert len(result) == 3  # 2 hidden + 1 failure


# ---------------------------------------------------------------------------
# _synthetic_constraints
# ---------------------------------------------------------------------------


def test_synthetic_constraints():
    oracle = TaskOracle(
        hidden_requirements=["h1"],
        success_indicators=SuccessIndicators(correctness=["s1"]),
        failure_modes=["f1"],
        evaluation_criteria=["e1"],
    )
    result = _synthetic_constraints(oracle)
    ids = [c.id for c in result]
    assert "auto_hidden_0" in ids
    assert "auto_success_0" in ids
    assert "auto_failure_INVERT_0" in ids
    assert "auto_criteria_0" in ids
    # Failure constraint should have expected=False
    fail_c = next(c for c in result if c.id == "auto_failure_INVERT_0")
    assert fail_c.expected is False


def test_synthetic_constraints_skips_empty():
    oracle = TaskOracle(hidden_requirements=["", "  ", "real"])
    result = _synthetic_constraints(oracle)
    assert len(result) == 1


# ---------------------------------------------------------------------------
# score_one — empty code guard
# ---------------------------------------------------------------------------


def test_score_one_empty_code(run_result, run_config):
    run_result.parsed_output.code = ""
    oracle = TaskOracle(hidden_requirements=["req"])
    result = score_one(run_result=run_result, oracle=oracle, cfg=run_config, provider_keys={})
    assert result.overall_score == 0.0
    assert result.passed is False


def test_score_one_whitespace_code(run_result, run_config):
    run_result.parsed_output.code = "   \n  "
    oracle = TaskOracle(hidden_requirements=["req"])
    result = score_one(run_result=run_result, oracle=oracle, cfg=run_config, provider_keys={})
    assert result.overall_score == 0.0


# ---------------------------------------------------------------------------
# score_one — with mock judge
# ---------------------------------------------------------------------------


@patch("vsevals.scorer.call_judge")
def test_score_one_constraint_binary(mock_judge, run_result, run_config):
    mock_judge.return_value = json.dumps({
        "results": [
            {"verdict": True, "reason": "correct API"},
            {"verdict": False, "reason": "no deprecated"},
        ]
    })
    oracle = TaskOracle(constraints=[
        OracleConstraint(id="c1", check="uses API", judge_prompt="check", expected=True),
        OracleConstraint(id="c2", check="no deprecated", judge_prompt="check", expected=False),
    ])
    result = score_one(run_result=run_result, oracle=oracle, cfg=run_config, provider_keys={})
    assert result.constraint_scoring_used is True
    assert result.constraint_checks_total == 2
    # c1: verdict=True, expected=True → satisfied
    # c2: verdict=False, expected=False → satisfied (not verdict)
    assert result.constraint_checks_passed == 2


@patch("vsevals.scorer.call_judge")
def test_score_one_legacy_weighted(mock_judge, run_result, run_config):
    mock_judge.return_value = json.dumps({
        "hidden": [True],
        "success": [True],
        "failure_modes": [False],
        "evaluation_criteria": [True],
    })
    run_config.scoring_primary_endpoint = "legacy_weighted"
    oracle = TaskOracle(
        hidden_requirements=["req"],
        success_indicators=SuccessIndicators(correctness=["ok"]),
        failure_modes=["fail"],
        evaluation_criteria=["crit"],
    )
    result = score_one(run_result=run_result, oracle=oracle, cfg=run_config, provider_keys={})
    assert result.constraint_scoring_used is False
    assert result.overall_score > 0


# ---------------------------------------------------------------------------
# _has_key
# ---------------------------------------------------------------------------


def test_has_key_from_api_key():
    from vsevals.scorer import _has_key

    cfg = RunConfig(api_key="some-key")
    assert _has_key("openai", cfg, {}) is True


def test_has_key_from_provider_api_keys():
    from vsevals.scorer import _has_key

    cfg = RunConfig(provider_api_keys={"anthropic": "ant-key"})
    assert _has_key("anthropic", cfg, {}) is True


def test_has_key_from_provider_keys_dict():
    from vsevals.scorer import _has_key

    cfg = RunConfig()
    assert _has_key("openai", cfg, {"openai": "ok-key"}) is True


def test_has_key_from_env_openai(monkeypatch):
    from vsevals.scorer import _has_key

    monkeypatch.setenv("OPENAI_API_KEY", "env-key")
    cfg = RunConfig()
    assert _has_key("openai", cfg, {}) is True


def test_has_key_from_env_anthropic(monkeypatch):
    from vsevals.scorer import _has_key

    monkeypatch.setenv("ANTHROPIC_API_KEY", "env-key")
    cfg = RunConfig()
    assert _has_key("anthropic", cfg, {}) is True


def test_has_key_unknown_provider_no_env():
    from vsevals.scorer import _has_key

    cfg = RunConfig()
    assert _has_key("unknown_provider", cfg, {}) is False


def test_has_key_no_sources(monkeypatch):
    from vsevals.scorer import _has_key

    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    cfg = RunConfig()
    assert _has_key("openai", cfg, {}) is False


# ---------------------------------------------------------------------------
# _judge_has_key
# ---------------------------------------------------------------------------


def test_judge_has_key_subprocess_providers():
    from vsevals.scorer import _judge_has_key

    cfg = RunConfig()
    for provider in ("claudecode", "codex", "mock"):
        assert _judge_has_key(f"{provider}:model", cfg, {}) is True


def test_judge_has_key_no_colon_defaults_to_openai():
    from vsevals.scorer import _judge_has_key

    cfg = RunConfig(api_key="key")
    assert _judge_has_key("gpt-5-mini", cfg, {}) is True


def test_judge_has_key_api_provider_with_key():
    from vsevals.scorer import _judge_has_key

    cfg = RunConfig(api_key="key")
    assert _judge_has_key("openai:gpt-5-mini", cfg, {}) is True


def test_judge_has_key_api_provider_no_key(monkeypatch):
    from vsevals.scorer import _judge_has_key

    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    cfg = RunConfig()
    assert _judge_has_key("openai:gpt-5-mini", cfg, {}) is False


# ---------------------------------------------------------------------------
# _call_judge_raw
# ---------------------------------------------------------------------------


@patch("vsevals.scorer.call_judge")
def test_call_judge_raw_delegates(mock_judge):
    from vsevals.scorer import _call_judge_raw

    mock_judge.return_value = '{"results": [true]}'
    cfg = RunConfig(api_key="key")
    result = _call_judge_raw("openai:gpt-5-mini", "instructions", "user_json", cfg, {})
    assert result == '{"results": [true]}'
    mock_judge.assert_called_once_with(
        model_name="openai:gpt-5-mini",
        system_prompt="instructions",
        user_prompt="user_json",
        cfg=cfg,
        provider_keys={},
    )


@patch("vsevals.scorer.call_judge")
def test_call_judge_raw_returns_none_on_failure(mock_judge):
    from vsevals.scorer import _call_judge_raw

    mock_judge.return_value = None
    cfg = RunConfig(api_key="key")
    result = _call_judge_raw("openai:gpt-5-mini", "inst", "uj", cfg, {})
    assert result is None


# ---------------------------------------------------------------------------
# score_one — routing paths
# ---------------------------------------------------------------------------


@patch("vsevals.scorer.call_judge")
def test_score_one_extracts_scoring_mode_from_cfg(mock_judge, run_result, run_config):
    """score_one reads scoring_match_mode and scoring_primary_endpoint from cfg."""
    mock_judge.return_value = json.dumps({
        "results": [{"verdict": True, "reason": "ok"}]
    })
    run_config.scoring_match_mode = "llm"
    run_config.scoring_primary_endpoint = "constraint_binary"
    oracle = TaskOracle(constraints=[
        OracleConstraint(id="c1", check="x", judge_prompt="x"),
    ])
    result = score_one(run_result=run_result, oracle=oracle, cfg=run_config, provider_keys={})
    assert result.constraint_scoring_used is True


@patch("vsevals.scorer.call_judge")
def test_score_one_auto_with_constraints_routes_constraint(mock_judge, run_result, run_config):
    """auto endpoint + explicit constraints → constraint binary path."""
    mock_judge.return_value = json.dumps({
        "results": [{"verdict": True, "reason": "ok"}]
    })
    run_config.scoring_primary_endpoint = "auto"
    oracle = TaskOracle(constraints=[
        OracleConstraint(id="c1", check="x", judge_prompt="x"),
    ])
    result = score_one(run_result=run_result, oracle=oracle, cfg=run_config, provider_keys={})
    assert result.constraint_scoring_used is True


@patch("vsevals.scorer.call_judge")
def test_score_one_auto_no_constraints_routes_legacy(mock_judge, run_result, run_config):
    """auto endpoint + no constraints + auto_constraints disabled → legacy path."""
    mock_judge.return_value = json.dumps({
        "hidden": [True],
        "success": [True],
        "failure_modes": [False],
        "evaluation_criteria": [True],
    })
    run_config.scoring_primary_endpoint = "auto"
    run_config.auto_constraints_from_legacy_oracle = False
    oracle = TaskOracle(
        hidden_requirements=["req"],
        success_indicators=SuccessIndicators(correctness=["ok"]),
        failure_modes=["fail"],
        evaluation_criteria=["crit"],
    )
    result = score_one(run_result=run_result, oracle=oracle, cfg=run_config, provider_keys={})
    assert result.constraint_scoring_used is False


# ---------------------------------------------------------------------------
# _score_constraints — full flow
# ---------------------------------------------------------------------------


@patch("vsevals.scorer.call_judge")
def test_score_constraints_all_pass(mock_judge, run_result, run_config):
    from vsevals.scorer import _score_constraints

    mock_judge.return_value = json.dumps({
        "results": [
            {"verdict": True, "reason": "good"},
            {"verdict": False, "reason": "absent"},
        ]
    })
    constraints = [
        OracleConstraint(id="c1", check="uses API", judge_prompt="check", expected=True),
        OracleConstraint(id="c2", check="no bad", judge_prompt="check", expected=False),
    ]
    result = _score_constraints(
        run_result=run_result, constraints=constraints,
        scoring_mode="llm", cfg=run_config, provider_keys={},
    )
    assert result.constraint_scoring_used is True
    assert result.constraint_checks_passed == 2
    assert result.constraint_checks_total == 2
    assert result.overall_score == 1.0
    assert result.passed is True


@patch("vsevals.scorer.call_judge")
def test_score_constraints_partial_fail(mock_judge, run_result, run_config):
    from vsevals.scorer import _score_constraints

    mock_judge.return_value = json.dumps({
        "results": [
            {"verdict": False, "reason": "missing"},
            {"verdict": True, "reason": "present"},
        ]
    })
    constraints = [
        OracleConstraint(id="c1", check="uses API", judge_prompt="check", expected=True),
        OracleConstraint(id="c2", check="no bad", judge_prompt="check", expected=False),
    ]
    result = _score_constraints(
        run_result=run_result, constraints=constraints,
        scoring_mode="llm", cfg=run_config, provider_keys={},
    )
    # c1: verdict=False, expected=True → NOT satisfied
    # c2: verdict=True, expected=False → NOT satisfied (not verdict = False)
    assert result.constraint_checks_passed == 0
    assert result.overall_score == 0.0


@patch("vsevals.scorer.call_judge")
def test_score_constraints_judge_returns_none(mock_judge, run_result, run_config):
    from vsevals.scorer import _score_constraints

    mock_judge.return_value = None
    constraints = [
        OracleConstraint(id="c1", check="x", judge_prompt="x"),
    ]
    result = _score_constraints(
        run_result=run_result, constraints=constraints,
        scoring_mode="llm", cfg=run_config, provider_keys={},
    )
    # No verdicts → llm_verdicts is None → all constraints fail
    assert result.constraint_checks_passed == 0
    assert result.overall_score == 0.0


@patch("vsevals.scorer.call_judge")
def test_score_constraints_constraint_results_detail(mock_judge, run_result, run_config):
    from vsevals.scorer import _score_constraints

    mock_judge.return_value = json.dumps({
        "results": [{"verdict": True, "reason": "found it"}]
    })
    constraints = [
        OracleConstraint(id="c1", check="x", judge_prompt="x", expected=True, voltsnip_key="key1"),
    ]
    result = _score_constraints(
        run_result=run_result, constraints=constraints,
        scoring_mode="llm", cfg=run_config, provider_keys={},
    )
    assert len(result.constraint_results) == 1
    cr = result.constraint_results[0]
    assert cr["id"] == "c1"
    assert cr["passed"] is True
    assert cr["llm_verdict"] is True
    assert cr["judge_reason"] == "found it"
    assert cr["expected"] is True
    assert cr["voltsnip_key"] == "key1"


@patch("vsevals.scorer.call_judge")
def test_score_constraints_slice_dim_auto_constraints(mock_judge, run_result, run_config):
    """When auto_constraints_from_legacy_oracle is True and constraints are auto_*, dims get sliced."""
    from vsevals.scorer import _score_constraints

    mock_judge.return_value = json.dumps({
        "results": [
            {"verdict": True, "reason": "ok"},
            {"verdict": False, "reason": "absent"},
        ]
    })
    run_config.auto_constraints_from_legacy_oracle = True
    constraints = [
        OracleConstraint(id="auto_hidden_0", check="x", judge_prompt="x", expected=True),
        OracleConstraint(id="auto_failure_INVERT_0", check="x", judge_prompt="x", expected=False),
    ]
    result = _score_constraints(
        run_result=run_result, constraints=constraints,
        scoring_mode="llm", cfg=run_config, provider_keys={},
    )
    # auto_hidden_0: verdict=True, expected=True → satisfied
    # auto_failure_INVERT_0: verdict=False, expected=False → satisfied
    assert result.hidden_requirements.total == 1
    assert result.hidden_requirements.matched == 1
    assert result.failure_modes.total == 1
    assert result.failure_modes.matched == 1
    # success_dim and criteria_dim: no constraints with those prefixes → neutral
    assert result.success_indicators.total == 0
    assert result.evaluation_criteria.total == 0


@patch("vsevals.scorer.call_judge")
def test_score_constraints_no_auto_prefix_dims_unified(mock_judge, run_result, run_config):
    """When constraints don't start with auto_, all dims point to the unified dim."""
    from vsevals.scorer import _score_constraints

    mock_judge.return_value = json.dumps({
        "results": [{"verdict": True, "reason": "ok"}]
    })
    run_config.auto_constraints_from_legacy_oracle = False
    constraints = [
        OracleConstraint(id="c1", check="x", judge_prompt="x", expected=True),
    ]
    result = _score_constraints(
        run_result=run_result, constraints=constraints,
        scoring_mode="llm", cfg=run_config, provider_keys={},
    )
    # With auto_constraints_from_legacy_oracle=False, all dims point to unified dim
    assert result.hidden_requirements.total == 1
    assert result.success_indicators.total == 1
    assert result.failure_modes.total == 1
    assert result.evaluation_criteria.total == 1


@patch("vsevals.scorer.call_judge")
def test_score_constraints_threshold(mock_judge, run_result, run_config):
    """Score below threshold → passed=False."""
    from vsevals.scorer import _score_constraints

    mock_judge.return_value = json.dumps({
        "results": [
            {"verdict": True, "reason": "ok"},
            {"verdict": False, "reason": "no"},
            {"verdict": False, "reason": "no"},
        ]
    })
    run_config.constraint_pass_threshold = 0.7
    constraints = [
        OracleConstraint(id="c1", check="x", judge_prompt="x", expected=True),
        OracleConstraint(id="c2", check="x", judge_prompt="x", expected=True),
        OracleConstraint(id="c3", check="x", judge_prompt="x", expected=True),
    ]
    result = _score_constraints(
        run_result=run_result, constraints=constraints,
        scoring_mode="llm", cfg=run_config, provider_keys={},
    )
    # 1/3 = 0.3333 < 0.7
    assert result.passed is False
    assert result.constraint_pass_threshold == 0.7


# ---------------------------------------------------------------------------
# _judge_constraints — paths
# ---------------------------------------------------------------------------


def test_judge_constraints_empty_constraints(run_result, run_config):
    from vsevals.scorer import _judge_constraints

    verdicts, audit, raw = _judge_constraints(
        run_result=run_result, constraints=[],
        cfg=run_config, provider_keys={},
    )
    assert verdicts is None
    assert audit is None
    assert raw is None


@patch("vsevals.scorer.call_judge")
def test_judge_constraints_single_judge(mock_judge, run_result, run_config):
    from vsevals.scorer import _judge_constraints

    mock_judge.return_value = json.dumps({
        "results": [{"verdict": True, "reason": "ok"}]
    })
    constraints = [
        OracleConstraint(id="c1", check="x", judge_prompt="x"),
    ]
    verdicts, audit, raw = _judge_constraints(
        run_result=run_result, constraints=constraints,
        cfg=run_config, provider_keys={},
    )
    assert verdicts is not None
    assert len(verdicts) == 1
    assert verdicts[0]["verdict"] is True
    assert audit is not None
    assert "instructions" in audit
    assert "user_json" in audit


@patch("vsevals.scorer.call_judge")
def test_judge_constraints_single_judge_returns_none(mock_judge, run_result, run_config):
    from vsevals.scorer import _judge_constraints

    mock_judge.return_value = None
    constraints = [
        OracleConstraint(id="c1", check="x", judge_prompt="x"),
    ]
    verdicts, audit, raw = _judge_constraints(
        run_result=run_result, constraints=constraints,
        cfg=run_config, provider_keys={},
    )
    assert verdicts is None
    assert audit is not None
    assert raw is None


@patch("vsevals.scorer.call_judge")
def test_judge_constraints_single_judge_bad_json(mock_judge, run_result, run_config):
    from vsevals.scorer import _judge_constraints

    mock_judge.return_value = "not json at all"
    constraints = [
        OracleConstraint(id="c1", check="x", judge_prompt="x"),
    ]
    verdicts, audit, raw = _judge_constraints(
        run_result=run_result, constraints=constraints,
        cfg=run_config, provider_keys={},
    )
    assert verdicts is None
    assert raw == "not json at all"


def test_judge_constraints_no_usable_specs(run_result, monkeypatch):
    from vsevals.scorer import _judge_constraints

    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    cfg = RunConfig(scoring_judge_model="openai:gpt-5-mini")
    constraints = [
        OracleConstraint(id="c1", check="x", judge_prompt="x"),
    ]
    verdicts, audit, raw = _judge_constraints(
        run_result=run_result, constraints=constraints,
        cfg=cfg, provider_keys={},
    )
    assert verdicts is None
    assert audit is not None  # audit is still built
    assert raw is None


@patch("vsevals.scorer.call_judge")
def test_judge_constraints_ensemble_parallel(mock_judge, run_result, run_config):
    from vsevals.scorer import _judge_constraints

    # Two judges return different verdicts
    call_count = [0]

    def _side_effect(**kwargs):
        call_count[0] += 1
        if call_count[0] == 1:
            return json.dumps({"results": [{"verdict": True, "reason": "j1"}]})
        return json.dumps({"results": [{"verdict": False, "reason": "j2"}]})

    mock_judge.side_effect = _side_effect
    run_config.scoring_judge_model = "mock:judge1+mock:judge2"
    constraints = [
        OracleConstraint(id="c1", check="x", judge_prompt="x", expected=True),
    ]
    verdicts, audit, raw = _judge_constraints(
        run_result=run_result, constraints=constraints,
        cfg=run_config, provider_keys={},
    )
    assert verdicts is not None
    # expected=True → LENIENT merge: any True → True
    assert verdicts[0]["verdict"] is True


@patch("vsevals.scorer.call_judge")
def test_judge_constraints_ensemble_all_fail_parse(mock_judge, run_result, run_config):
    """When all ensemble judges return unparseable responses, verdicts are None."""
    from vsevals.scorer import _judge_constraints

    mock_judge.return_value = "garbage"
    run_config.scoring_judge_model = "mock:j1+mock:j2"
    constraints = [OracleConstraint(id="c1", check="x", judge_prompt="x")]
    verdicts, audit, raw = _judge_constraints(
        run_result=run_result, constraints=constraints,
        cfg=run_config, provider_keys={},
    )
    assert verdicts is None


@patch("vsevals.scorer.call_judge")
def test_judge_constraints_ensemble_single_success(mock_judge, run_result, run_config):
    """Ensemble: one judge succeeds, one fails → returns the successful verdict."""
    from vsevals.scorer import _judge_constraints

    call_count = [0]

    def _side_effect(**kwargs):
        call_count[0] += 1
        if call_count[0] == 1:
            return json.dumps({"results": [{"verdict": True, "reason": "ok"}]})
        return None  # second judge fails

    mock_judge.side_effect = _side_effect
    run_config.scoring_judge_model = "mock:j1+mock:j2"
    constraints = [OracleConstraint(id="c1", check="x", judge_prompt="x")]
    verdicts, audit, raw = _judge_constraints(
        run_result=run_result, constraints=constraints,
        cfg=run_config, provider_keys={},
    )
    assert verdicts is not None
    assert verdicts[0]["verdict"] is True


# ---------------------------------------------------------------------------
# _score_legacy — full flow
# ---------------------------------------------------------------------------


@patch("vsevals.scorer.call_judge")
def test_score_legacy_weighted_scoring(mock_judge, run_result, run_config):
    from vsevals.scorer import _score_legacy

    mock_judge.return_value = json.dumps({
        "hidden": [True, False],
        "success": [True],
        "failure_modes": [False],
        "evaluation_criteria": [True],
    })
    oracle = TaskOracle(
        hidden_requirements=["req1", "req2"],
        success_indicators=SuccessIndicators(correctness=["ok"]),
        failure_modes=["fail"],
        evaluation_criteria=["crit"],
    )
    result = _score_legacy(
        run_result=run_result, oracle=oracle,
        scoring_mode="llm", cfg=run_config, provider_keys={},
    )
    assert result.constraint_scoring_used is False
    # hidden: 1/2 = 0.5
    assert result.hidden_requirements.matched == 1
    assert result.hidden_requirements.total == 2
    # success: 1/1 = 1.0
    assert result.success_indicators.matched == 1
    # failure_modes: inverted; verdict=False → matched (not present)
    assert result.failure_modes.matched == 1
    # criteria: 1/1 = 1.0
    assert result.evaluation_criteria.matched == 1
    # Overall: 0.40*0.5 + 0.30*1.0 + 0.20*1.0 + 0.10*1.0 = 0.20+0.30+0.20+0.10 = 0.80
    assert result.overall_score == pytest.approx(0.80, abs=0.01)


@patch("vsevals.scorer.call_judge")
def test_score_legacy_all_pass(mock_judge, run_result, run_config):
    from vsevals.scorer import _score_legacy

    mock_judge.return_value = json.dumps({
        "hidden": [True],
        "success": [True],
        "failure_modes": [False],
        "evaluation_criteria": [True],
    })
    oracle = TaskOracle(
        hidden_requirements=["req"],
        success_indicators=SuccessIndicators(correctness=["ok"]),
        failure_modes=["fail"],
        evaluation_criteria=["crit"],
    )
    result = _score_legacy(
        run_result=run_result, oracle=oracle,
        scoring_mode="llm", cfg=run_config, provider_keys={},
    )
    assert result.overall_score == 1.0
    assert result.passed is True


@patch("vsevals.scorer.call_judge")
def test_score_legacy_all_fail(mock_judge, run_result, run_config):
    from vsevals.scorer import _score_legacy

    mock_judge.return_value = json.dumps({
        "hidden": [False],
        "success": [False],
        "failure_modes": [True],   # failure present → inverted → miss
        "evaluation_criteria": [False],
    })
    oracle = TaskOracle(
        hidden_requirements=["req"],
        success_indicators=SuccessIndicators(correctness=["ok"]),
        failure_modes=["fail"],
        evaluation_criteria=["crit"],
    )
    result = _score_legacy(
        run_result=run_result, oracle=oracle,
        scoring_mode="llm", cfg=run_config, provider_keys={},
    )
    assert result.overall_score == 0.0
    assert result.passed is False


@patch("vsevals.scorer.call_judge")
def test_score_legacy_dim_notes(mock_judge, run_result, run_config):
    """_dim generates notes for misses, including 'not found' and 'present (bad)' labels."""
    from vsevals.scorer import _score_legacy

    mock_judge.return_value = json.dumps({
        "hidden": [False],
        "success": [],
        "failure_modes": [True],
        "evaluation_criteria": [],
    })
    oracle = TaskOracle(
        hidden_requirements=["must use correct API"],
        success_indicators=SuccessIndicators(),
        failure_modes=["uses deprecated method"],
        evaluation_criteria=[],
    )
    result = _score_legacy(
        run_result=run_result, oracle=oracle,
        scoring_mode="llm", cfg=run_config, provider_keys={},
    )
    assert any("not found" in n for n in result.hidden_requirements.notes)
    assert any("present (bad)" in n for n in result.failure_modes.notes)


@patch("vsevals.scorer.call_judge")
def test_score_legacy_empty_dims(mock_judge, run_result, run_config):
    """Empty oracle dimensions → score=1.0 (neutral)."""
    from vsevals.scorer import _score_legacy

    mock_judge.return_value = json.dumps({
        "hidden": [], "success": [], "failure_modes": [], "evaluation_criteria": [],
    })
    oracle = TaskOracle()
    result = _score_legacy(
        run_result=run_result, oracle=oracle,
        scoring_mode="llm", cfg=run_config, provider_keys={},
    )
    assert result.hidden_requirements.score == 1.0
    assert result.success_indicators.score == 1.0
    assert result.failure_modes.score == 1.0
    assert result.evaluation_criteria.score == 1.0
    assert result.overall_score == 1.0


@patch("vsevals.scorer.call_judge")
def test_score_legacy_judge_unavailable(mock_judge, run_result, monkeypatch):
    """When judge has no key, llm_results is all None → dim scores are 0."""
    from vsevals.scorer import _score_legacy

    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    cfg = RunConfig(scoring_judge_model="openai:gpt-5-mini")
    oracle = TaskOracle(
        hidden_requirements=["req"],
        success_indicators=SuccessIndicators(correctness=["ok"]),
        failure_modes=["fail"],
        evaluation_criteria=["crit"],
    )
    result = _score_legacy(
        run_result=run_result, oracle=oracle,
        scoring_mode="llm", cfg=cfg, provider_keys={},
    )
    # No judge available → all None → matched=0 for non-empty dims
    assert result.hidden_requirements.matched == 0
    assert result.hidden_requirements.total == 1


# ---------------------------------------------------------------------------
# _judge_requirements — paths
# ---------------------------------------------------------------------------


@patch("vsevals.scorer.call_judge")
def test_judge_requirements_single_judge(mock_judge, run_result, run_config):
    from vsevals.scorer import _judge_requirements

    mock_judge.return_value = json.dumps({
        "hidden": [True],
        "success": [True],
        "failure_modes": [False],
        "evaluation_criteria": [True],
    })
    oracle = TaskOracle(
        hidden_requirements=["req"],
        success_indicators=SuccessIndicators(correctness=["ok"]),
        failure_modes=["fail"],
        evaluation_criteria=["crit"],
    )
    result = _judge_requirements(
        run_result=run_result, oracle=oracle,
        cfg=run_config, provider_keys={},
    )
    assert result["hidden"] == [True]
    assert result["success"] == [True]
    assert result["failure_modes"] == [False]
    assert result["evaluation_criteria"] == [True]


def test_judge_requirements_no_usable_specs(run_result, monkeypatch):
    from vsevals.scorer import _judge_requirements

    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    cfg = RunConfig(scoring_judge_model="openai:gpt-5-mini")
    oracle = TaskOracle(hidden_requirements=["req"])
    result = _judge_requirements(
        run_result=run_result, oracle=oracle,
        cfg=cfg, provider_keys={},
    )
    assert result == {"hidden": None, "success": None, "failure_modes": None, "evaluation_criteria": None}


@patch("vsevals.scorer.call_judge")
def test_judge_requirements_ensemble_parallel(mock_judge, run_result, run_config):
    from vsevals.scorer import _judge_requirements

    call_count = [0]

    def _side_effect(**kwargs):
        call_count[0] += 1
        if call_count[0] == 1:
            return json.dumps({
                "hidden": [True],
                "success": [False],
                "failure_modes": [True],
                "evaluation_criteria": [True],
            })
        return json.dumps({
            "hidden": [False],
            "success": [True],
            "failure_modes": [False],
            "evaluation_criteria": [False],
        })

    mock_judge.side_effect = _side_effect
    run_config.scoring_judge_model = "mock:j1+mock:j2"
    oracle = TaskOracle(
        hidden_requirements=["req"],
        success_indicators=SuccessIndicators(correctness=["ok"]),
        failure_modes=["fail"],
        evaluation_criteria=["crit"],
    )
    result = _judge_requirements(
        run_result=run_result, oracle=oracle,
        cfg=run_config, provider_keys={},
    )
    # hidden: LENIENT → any True → True
    assert result["hidden"] == [True]
    # success: LENIENT → any True → True
    assert result["success"] == [True]
    # failure_modes: STRICT → all True → False (not all)
    assert result["failure_modes"] == [False]
    # evaluation_criteria: LENIENT → any True → True
    assert result["evaluation_criteria"] == [True]


@patch("vsevals.scorer.call_judge")
def test_judge_requirements_parse_one_bad_json(mock_judge, run_result, run_config):
    from vsevals.scorer import _judge_requirements

    mock_judge.return_value = "not json"
    oracle = TaskOracle(hidden_requirements=["req"])
    result = _judge_requirements(
        run_result=run_result, oracle=oracle,
        cfg=run_config, provider_keys={},
    )
    assert result == {"hidden": None, "success": None, "failure_modes": None, "evaluation_criteria": None}


@patch("vsevals.scorer.call_judge")
def test_judge_requirements_ensemble_all_fail_parse(mock_judge, run_result, run_config):
    from vsevals.scorer import _judge_requirements

    mock_judge.return_value = "garbage"
    run_config.scoring_judge_model = "mock:j1+mock:j2"
    oracle = TaskOracle(hidden_requirements=["req"])
    result = _judge_requirements(
        run_result=run_result, oracle=oracle,
        cfg=run_config, provider_keys={},
    )
    assert result == {"hidden": None, "success": None, "failure_modes": None, "evaluation_criteria": None}


# ---------------------------------------------------------------------------
# _synthetic_constraints — _add_failure_set branch
# ---------------------------------------------------------------------------


def test_synthetic_constraints_failure_set_expected_false():
    """Failure mode constraints are created with expected=False."""
    oracle = TaskOracle(failure_modes=["uses deprecated method", "crashes on empty input"])
    result = _synthetic_constraints(oracle)
    assert len(result) == 2
    for c in result:
        assert c.expected is False
        assert "auto_failure_INVERT_" in c.id
        assert "failure mode" in c.judge_prompt


def test_synthetic_constraints_failure_set_skips_empty():
    """Empty/whitespace failure modes are skipped."""
    oracle = TaskOracle(failure_modes=["real failure", "", "  "])
    result = _synthetic_constraints(oracle)
    assert len(result) == 1
    assert result[0].id == "auto_failure_INVERT_0"


def test_synthetic_constraints_all_four_sets():
    """All four sets produce constraints with correct prefixes."""
    oracle = TaskOracle(
        hidden_requirements=["h1", "h2"],
        success_indicators=SuccessIndicators(correctness=["s1"]),
        failure_modes=["f1"],
        evaluation_criteria=["e1", "e2", "e3"],
    )
    result = _synthetic_constraints(oracle)
    ids = [c.id for c in result]
    assert ids.count("auto_hidden_0") == 1
    assert ids.count("auto_hidden_1") == 1
    assert ids.count("auto_success_0") == 1
    assert ids.count("auto_failure_INVERT_0") == 1
    assert ids.count("auto_criteria_0") == 1
    assert ids.count("auto_criteria_1") == 1
    assert ids.count("auto_criteria_2") == 1
    # Verify expected values
    for c in result:
        if "failure_INVERT" in c.id:
            assert c.expected is False
        else:
            assert c.expected is True


# ---------------------------------------------------------------------------
# Judge prompt variant (line 329-339)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("variant,expected_fragment", [
    ("verdict-true", '"verdict":true'),
    ("verdict-false", '"verdict":false'),
    ("none", '"verdict":<bool>'),
    ("pre-67f6ed0", '"verdict":false,"reason":"1-sentence explanation"'),
    ("both", '{"verdict":true,"reason":"..."},{"verdict":false,"reason":"..."}'),
])
@patch("vsevals.scorer.call_judge")
def test_judge_prompt_variant_in_instructions(mock_judge, variant, expected_fragment, run_result, run_config):
    """Each judge_prompt_variant produces a distinct format example in the instructions."""
    from vsevals.scorer import _judge_constraints

    mock_judge.return_value = json.dumps({"results": [{"verdict": True, "reason": "ok"}]})
    run_config.judge_prompt_variant = variant
    constraints = [OracleConstraint(id="c1", check="x", judge_prompt="x")]
    _verdicts, audit, _raw = _judge_constraints(
        run_result=run_result, constraints=constraints,
        cfg=run_config, provider_keys={},
    )
    assert audit is not None
    assert expected_fragment in audit["instructions"]


@patch("vsevals.scorer.call_judge")
def test_judge_prompt_variant_default_is_both(mock_judge, run_result, run_config):
    """Default judge_prompt_variant is 'both'."""
    from vsevals.scorer import _judge_constraints

    mock_judge.return_value = json.dumps({"results": [{"verdict": True, "reason": "ok"}]})
    # run_config has judge_prompt_variant="both" by default from RunConfig
    constraints = [OracleConstraint(id="c1", check="x", judge_prompt="x")]
    _verdicts, audit, _raw = _judge_constraints(
        run_result=run_result, constraints=constraints,
        cfg=run_config, provider_keys={},
    )
    assert '{"verdict":true,"reason":"..."},{"verdict":false,"reason":"..."}' in audit["instructions"]
