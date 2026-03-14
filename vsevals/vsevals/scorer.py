"""Scoring pipeline: constraint-binary (default) or legacy-weighted (fallback).

Constraint binary: each OracleConstraint judged pass/fail; overall = passed/total; threshold=0.7.
Legacy weighted: 40% hidden + 30% success + 20% failure + 10% criteria; pass if overall>=0.70,
  hidden>=0.50, failure>=0.60. All scoring is LLM-judge-only.

Ensemble: scoring_judge_model may be '+'-delimited (e.g. "openai:gpt-5.2+anthropic:claude-opus-4-6").
  Judges run in parallel; verdicts merged: LENIENT (any=True) for expected=True/hidden/success/criteria,
  STRICT (all=True) for expected=False/failure_modes.
"""

from __future__ import annotations

import json
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

from vsevals.dispatch import call_judge
from vsevals.models import OracleConstraint, RunConfig, RunResult, ScoreDimension, ScoreResult, TaskOracle

LOGGER = logging.getLogger(__name__)


def _parse_ensemble(spec: str) -> list[str]:
    return [m.strip() for m in spec.split("+") if m.strip()]


def _call_judge_raw(judge_model: str, instructions: str, user_json: str, cfg: RunConfig, provider_keys: dict[str, str]) -> str | None:
    return call_judge(model_name=judge_model, system_prompt=instructions, user_prompt=user_json, cfg=cfg, provider_keys=provider_keys)


def _run_ensemble(usable_specs: list[str], instructions: str, user_json: str, cfg: RunConfig, provider_keys: dict[str, str]) -> tuple[list[str | None], str | None]:
    raw_results: list[str | None] = []
    first_raw: str | None = None
    with ThreadPoolExecutor(max_workers=len(usable_specs)) as ex:
        for future in as_completed({ex.submit(_call_judge_raw, s, instructions, user_json, cfg, provider_keys): s for s in usable_specs}):
            raw = future.result()
            raw_results.append(raw)
            if raw and first_raw is None:
                first_raw = raw
    return raw_results, first_raw


def _merge_verdicts_by_index(items_per_judge: list[list], n: int, strict_fn) -> list:
    result = []
    for i in range(n):
        votes = [bl[i] for bl in items_per_judge if i < len(bl)]
        result.append(False if not votes else strict_fn(votes))
    return result


def _merge_constraint_verdicts(verdict_lists: list[list[dict]], constraints: list[OracleConstraint]) -> list[dict]:
    n = len(constraints)
    result: list[dict] = []
    for i in range(n):
        items = [bl[i] for bl in verdict_lists if i < len(bl)]
        if not items:
            result.append({"verdict": False, "reason": None})
            continue
        votes = [item["verdict"] for item in items]
        merged_verdict = any(votes) if constraints[i].expected else all(votes)
        reason = next((item["reason"] for item in items if item["verdict"] == merged_verdict and item.get("reason")), None)
        result.append({"verdict": merged_verdict, "reason": reason})
    return result


def _merge_requirement_verdicts(results_per_dim: list[dict[str, list[bool] | None]], lengths: dict[str, int]) -> dict[str, list[bool] | None]:
    if not results_per_dim:
        return {k: None for k in lengths}
    if len(results_per_dim) == 1:
        return results_per_dim[0]
    merged: dict[str, list[bool] | None] = {}
    for dim, length in lengths.items():
        lists = [r[dim] for r in results_per_dim if r.get(dim) is not None]
        if not lists:
            merged[dim] = None
        elif len(lists) == 1:
            merged[dim] = lists[0]
        else:
            strict_fn = all if dim == "failure_modes" else any
            merged[dim] = _merge_verdicts_by_index(lists, length, strict_fn)
    return merged


def score_one(*, run_result: RunResult, oracle: TaskOracle, cfg: RunConfig, provider_keys: dict[str, str]) -> ScoreResult:
    code = (run_result.parsed_output.code or "").strip()
    if not code:
        LOGGER.warning("score_one: empty code output, returning zero score")
        zero_dim = ScoreDimension(matched=0, total=1, score=0.0, notes=["no code produced"])
        neutral = ScoreDimension(matched=0, total=0, score=1.0, notes=[])
        return ScoreResult(overall_score=0.0, passed=False, hidden_requirements=zero_dim,
                           success_indicators=neutral, failure_modes=neutral, evaluation_criteria=neutral,
                           constraint_scoring_used=False)

    endpoint = (cfg.scoring_primary_endpoint or "auto").lower()
    constraints = _select_constraints(oracle, endpoint, cfg)
    if constraints:
        return _score_constraints(run_result=run_result, constraints=constraints,
                                  scoring_mode=(cfg.scoring_match_mode or "llm").lower(),
                                  cfg=cfg, provider_keys=provider_keys)
    return _score_legacy(run_result=run_result, oracle=oracle,
                         scoring_mode=(cfg.scoring_match_mode or "llm").lower(),
                         cfg=cfg, provider_keys=provider_keys)


def _score_constraints(*, run_result: RunResult, constraints: list[OracleConstraint], scoring_mode: str, cfg: RunConfig, provider_keys: dict[str, str]) -> ScoreResult:
    threshold = float(cfg.constraint_pass_threshold)
    llm_verdicts, judge_audit, judge_raw = _judge_constraints(run_result=run_result, constraints=constraints, cfg=cfg, provider_keys=provider_keys)

    passed_count = 0
    misses: list[str] = []
    constraint_results: list[dict] = []

    for idx, constraint in enumerate(constraints):
        judged_item = (llm_verdicts[idx] if llm_verdicts is not None and idx < len(llm_verdicts) else None)
        verdict = bool(judged_item["verdict"]) if isinstance(judged_item, dict) else bool(judged_item)
        reason = judged_item.get("reason") if isinstance(judged_item, dict) else None
        satisfied = verdict if constraint.expected else not verdict
        if satisfied:
            passed_count += 1
        else:
            misses.append(constraint.id)
        constraint_results.append({"id": constraint.id, "passed": satisfied, "llm_verdict": verdict,
                                    "judge_reason": reason, "expected": constraint.expected,
                                    "voltsnip_key": constraint.voltsnip_key})

    total = len(constraints)
    overall = round(passed_count / total, 4) if total > 0 else 1.0
    dim = ScoreDimension(matched=passed_count, total=total, score=overall, notes=[f"missing: {m}" for m in misses])

    def _slice_dim(prefix: str) -> ScoreDimension:
        notes = [n for n in dim.notes if f"missing: {prefix}" in n]
        count = sum(1 for c in constraints if c.id.startswith(prefix))
        if count == 0:
            return ScoreDimension(matched=0, total=0, score=1.0, notes=[])
        failures = sum(1 for n in notes if "missing:" in n)
        matched = count - failures
        return ScoreDimension(matched=matched, total=count, score=round(matched / count, 4) if count > 0 else 1.0, notes=notes)

    neutral = ScoreDimension(matched=0, total=0, score=1.0, notes=[])
    if cfg.auto_constraints_from_legacy_oracle and any(c.id.startswith("auto_") for c in constraints):
        hidden_dim, success_dim, failure_dim, criteria_dim = (
            _slice_dim("auto_hidden_"), _slice_dim("auto_success_"),
            _slice_dim("auto_failure_INVERT_"), _slice_dim("auto_criteria_"),
        )
    else:
        hidden_dim = success_dim = failure_dim = criteria_dim = dim

    return ScoreResult(overall_score=overall, passed=overall >= threshold,
                       hidden_requirements=hidden_dim, success_indicators=success_dim,
                       failure_modes=failure_dim, evaluation_criteria=criteria_dim,
                       evaluation_criteria_notes=[c.id for c in constraints],
                       constraint_scoring_used=True, constraint_checks_passed=passed_count,
                       constraint_checks_total=total, constraint_pass_threshold=threshold,
                       constraint_results=constraint_results, judge_payload=judge_audit,
                       judge_raw_response=judge_raw)


def _judge_constraints(*, run_result: RunResult, constraints: list[OracleConstraint], cfg: RunConfig, provider_keys: dict[str, str]) -> tuple[list[dict] | None, dict | None, str | None]:
    if not constraints:
        return None, None, None

    judge_specs = _parse_ensemble(cfg.scoring_judge_model)
    payload = {
        "candidate": {"code": run_result.parsed_output.code, "comments": run_result.parsed_output.comments},
        "constraints": [{"id": c.id, "voltsnip_key": c.voltsnip_key, "check": c.check, "judge_prompt": c.judge_prompt} for c in constraints],
    }
    _fmt = {"verdict-true": '{"results":[{"verdict":true,"reason":"..."},...]} ',
            "verdict-false": '{"results":[{"verdict":false,"reason":"..."},...]} ',
            "none": '{"results":[{"verdict":<bool>,"reason":"<explanation>"},...]} ',
            "pre-67f6ed0": '{"results":[{"verdict":false,"reason":"1-sentence explanation"},...]} '}
    fmt_example = _fmt.get(getattr(cfg, "judge_prompt_variant", "both"), '{"results":[{"verdict":true,"reason":"..."},{"verdict":false,"reason":"..."},...]} ')
    instructions = ("Judge each constraint independently as pass/fail for this candidate output. "
                    "Use judge_prompt as the primary decision rule. "
                    "Answer true if the described behavior IS present; false if it is NOT present. "
                    f"Return ONLY JSON: {fmt_example}in the same order as input constraints. "
                    "verdict must be a JSON boolean (true or false), not a string.")
    user_json = json.dumps(payload, ensure_ascii=False)
    audit = {"instructions": instructions, "user_json": user_json}

    usable_specs = [s for s in judge_specs if _judge_has_key(s, cfg, provider_keys)]
    if not usable_specs:
        LOGGER.debug("constraint judge skipped: no usable judge in spec=%s", cfg.scoring_judge_model)
        return None, audit, None

    if len(usable_specs) == 1:
        raw = _call_judge_raw(usable_specs[0], instructions, user_json, cfg, provider_keys)
        if not raw:
            return None, audit, None
        parsed = _parse_json(raw)
        if parsed is None:
            return None, audit, raw
        return _coerce_verdict_list(parsed.get("results"), len(constraints)), audit, raw

    raw_results, first_raw = _run_ensemble(usable_specs, instructions, user_json, cfg, provider_keys)
    verdict_lists = [vl for raw in raw_results if raw
                     for parsed in [_parse_json(raw)] if parsed
                     for vl in [_coerce_verdict_list(parsed.get("results"), len(constraints))] if vl is not None]
    for vl in verdict_lists:
        LOGGER.debug("ensemble constraint judge verdicts=%s", [v["verdict"] for v in vl])
    if not verdict_lists:
        return None, audit, first_raw
    return (verdict_lists[0] if len(verdict_lists) == 1 else _merge_constraint_verdicts(verdict_lists, constraints)), audit, first_raw


def _score_legacy(*, run_result: RunResult, oracle: TaskOracle, scoring_mode: str, cfg: RunConfig, provider_keys: dict[str, str]) -> ScoreResult:
    llm_results = _judge_requirements(run_result=run_result, oracle=oracle, cfg=cfg, provider_keys=provider_keys)

    def _dim(lines: list[str], llm_hits: list[bool] | None, *, invert: bool = False) -> ScoreDimension:
        if not lines:
            return ScoreDimension(matched=0, total=0, score=1.0, notes=[])
        hits, notes = 0, []
        for i, line in enumerate(lines):
            matched = not bool(llm_hits[i] if llm_hits and i < len(llm_hits) else None) if invert else bool(llm_hits[i] if llm_hits and i < len(llm_hits) else None)
            if matched:
                hits += 1
            else:
                notes.append(f"{'present (bad)' if invert else 'not found'}: {line[:60]}")
        return ScoreDimension(matched=hits, total=len(lines), score=round(hits / len(lines), 4), notes=notes)

    hidden_dim = _dim(oracle.hidden_requirements, llm_results.get("hidden"))
    success_dim = _dim(oracle.success_indicators.as_lines(), llm_results.get("success"))
    failure_dim_ = _dim(oracle.failure_modes, llm_results.get("failure_modes"), invert=True)
    criteria_dim = _dim(oracle.evaluation_criteria, llm_results.get("evaluation_criteria"))
    overall = round(0.40 * hidden_dim.score + 0.30 * success_dim.score + 0.20 * failure_dim_.score + 0.10 * criteria_dim.score, 4)
    legacy_passed = overall >= 0.70 and hidden_dim.score >= 0.50 and failure_dim_.score >= 0.60
    return ScoreResult(overall_score=overall, passed=legacy_passed, hidden_requirements=hidden_dim,
                       success_indicators=success_dim, failure_modes=failure_dim_,
                       evaluation_criteria=criteria_dim, constraint_scoring_used=False)


def _judge_requirements(*, run_result: RunResult, oracle: TaskOracle, cfg: RunConfig, provider_keys: dict[str, str]) -> dict[str, list[bool] | None]:
    empty: dict[str, list[bool] | None] = {"hidden": None, "success": None, "failure_modes": None, "evaluation_criteria": None}
    usable_specs = [s for s in _parse_ensemble(cfg.scoring_judge_model) if _judge_has_key(s, cfg, provider_keys)]
    if not usable_specs:
        return empty

    hidden, success, failures, criteria = (oracle.hidden_requirements, oracle.success_indicators.as_lines(),
                                             oracle.failure_modes, oracle.evaluation_criteria)
    payload = {"candidate": {"code": run_result.parsed_output.code, "comments": run_result.parsed_output.comments},
               "requirements": {"hidden": hidden, "success": success, "failure_modes": failures, "evaluation_criteria": criteria}}
    instructions = ("Evaluate whether each requirement is satisfied by the candidate code/comments. "
                    "For failure_modes, mark true only when the failure behavior is actually present. "
                    "Return ONLY JSON with arrays of booleans: hidden, success, failure_modes, evaluation_criteria.")
    user_json = json.dumps(payload, ensure_ascii=False)
    lengths = {"hidden": len(hidden), "success": len(success), "failure_modes": len(failures), "evaluation_criteria": len(criteria)}

    def _parse_one(raw: str | None) -> dict[str, list[bool] | None] | None:
        if not raw:
            return None
        parsed = _parse_json(raw)
        return None if parsed is None else {
            "hidden": _coerce_bool_list(parsed.get("hidden"), len(hidden)),
            "success": _coerce_bool_list(parsed.get("success"), len(success)),
            "failure_modes": _coerce_bool_list(parsed.get("failure_modes"), len(failures)),
            "evaluation_criteria": _coerce_bool_list(parsed.get("evaluation_criteria"), len(criteria)),
        }

    if len(usable_specs) == 1:
        result = _parse_one(_call_judge_raw(usable_specs[0], instructions, user_json, cfg, provider_keys))
        return result if result is not None else empty

    raw_results, _ = _run_ensemble(usable_specs, instructions, user_json, cfg, provider_keys)
    results_per_judge = [r for raw in raw_results if raw and (r := _parse_one(raw)) is not None]
    return _merge_requirement_verdicts(results_per_judge, lengths) if results_per_judge else empty


def _select_constraints(oracle: TaskOracle, endpoint: str, cfg: RunConfig) -> list[OracleConstraint]:
    if endpoint == "legacy_weighted":
        return []
    if oracle.constraints and endpoint in ("constraint_binary", "auto"):
        return oracle.constraints
    if endpoint == "auto" and cfg.auto_constraints_from_legacy_oracle:
        return _synthetic_constraints(oracle)
    return []


def _synthetic_constraints(oracle: TaskOracle) -> list[OracleConstraint]:
    constraints: list[OracleConstraint] = []

    def _add(items: list[str], prefix: str, prompt_template: str, expected: bool = True) -> None:
        for i, item in enumerate(items):
            if item := item.strip():
                constraints.append(OracleConstraint(id=f"{prefix}_{i}", check=item,
                                                     judge_prompt=prompt_template.format(item=item), expected=expected))

    _add(oracle.hidden_requirements, "auto_hidden", "Does the implementation satisfy: {item}")
    _add(oracle.success_indicators.as_lines(), "auto_success", "Does the implementation include: {item}")
    _add(oracle.failure_modes, "auto_failure_INVERT", "Does the implementation exhibit this failure mode: {item}", expected=False)
    _add(oracle.evaluation_criteria, "auto_criteria", "Does the implementation satisfy this criteria: {item}")
    return constraints


def _has_key(provider: str, cfg: RunConfig, provider_keys: dict[str, str]) -> bool:
    import os
    if cfg.api_key or provider in cfg.provider_api_keys or provider in provider_keys:
        return True
    env_map = {"openai": "OPENAI_API_KEY", "anthropic": "ANTHROPIC_API_KEY"}
    return bool((env_k := env_map.get(provider)) and os.environ.get(env_k))


def _judge_has_key(judge_model: str, cfg: RunConfig, provider_keys: dict[str, str]) -> bool:
    provider = judge_model.split(":")[0].lower() if ":" in judge_model else "openai"
    if provider in ("claudecode", "codex", "mock"):
        return True
    return _has_key(provider, cfg, provider_keys)


def _parse_json(text: str) -> dict[str, Any] | None:
    text = text.strip()
    try:
        obj = json.loads(text)
        return obj if isinstance(obj, dict) else None
    except Exception:
        pass
    depth, start, in_str, escaped = 0, None, False, False
    for i, ch in enumerate(text):
        if in_str:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == "{":
            if depth == 0:
                start = i
            depth += 1
        elif ch == "}" and depth > 0:
            depth -= 1
            if depth == 0 and start is not None:
                try:
                    obj = json.loads(text[start:i + 1])
                    return obj if isinstance(obj, dict) else None
                except Exception:
                    pass
                start = None
    return None


def _coerce_bool_list(raw: Any, expected_len: int) -> list[bool] | None:
    if not isinstance(raw, list):
        return None
    result = [bool(v) if isinstance(v, (bool, int)) else False for v in raw]
    result.extend([False] * max(0, expected_len - len(result)))
    return result[:expected_len]


def _coerce_verdict_list(raw: Any, expected_len: int) -> list[dict] | None:
    if not isinstance(raw, list):
        return None
    result: list[dict] = []
    for v in raw:
        if isinstance(v, dict):
            r = v.get("reason")
            result.append({"verdict": bool(v.get("verdict", False)), "reason": str(r).strip() if r else None})
        else:
            result.append({"verdict": bool(v) if isinstance(v, (bool, int)) else False, "reason": None})
    result.extend([{"verdict": False, "reason": None}] * max(0, expected_len - len(result)))
    return result[:expected_len]
