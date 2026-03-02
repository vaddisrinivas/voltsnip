"""Scoring pipeline.

Two endpoints (selected automatically or via RunConfig.scoring_primary_endpoint):

1. Constraint binary (default when task has constraints):
   - Each OracleConstraint is judged pass/fail by an LLM judge.
   - Overall = passed_count / total.  Threshold default = 0.7.
   - This is the mode used for publication runs.

2. Legacy weighted (fallback when no constraints defined):
   - Weighted sum: 40% hidden_requirements + 30% success_indicators
                    + 20% failure_modes + 10% evaluation_criteria
   - Each dimension: LLM-judged matching.
   - Pass if overall >= 0.70 AND hidden >= 0.5 AND failure >= 0.6.

All scoring is LLM-judge-only — no lexical / substring matching.
String matching is too brittle for code semantics: a model that writes
`if code >= 500 or code == 429` is equally correct as one that writes
`- {404}`, but a keyword check would treat them differently.

Ensemble judges:
  scoring_judge_model may contain '+'-separated models, e.g.
  "openai:gpt-5.2+anthropic:claude-opus-4-6".
  All judges are called in parallel.  Verdicts are merged per dimension:
    - expected=True constraints / hidden,success,criteria: LENIENT (any True → True)
    - expected=False constraints / failure_modes:          STRICT  (all True → True)
  This eliminates false failures caused by unreliable small judges on
  failure-absent checks while keeping full sensitivity on positive checks.
"""

from __future__ import annotations

import json
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

from vsevals.dispatch import call_judge
from vsevals.models import (
    OracleConstraint,
    RunConfig,
    RunResult,
    ScoreDimension,
    ScoreResult,
    TaskOracle,
)

LOGGER = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Ensemble judge helpers
# ---------------------------------------------------------------------------


def _parse_ensemble(spec: str) -> list[str]:
    """Split '+'-delimited ensemble spec → list of model names."""
    return [m.strip() for m in spec.split("+") if m.strip()]


def _call_judge_raw(
    judge_model: str,
    instructions: str,
    user_json: str,
    cfg: RunConfig,
    provider_keys: dict[str, str],
) -> str | None:
    """Call one judge model; return raw text or None on failure."""
    return call_judge(
        model_name=judge_model,
        system_prompt=instructions,
        user_prompt=user_json,
        cfg=cfg,
        provider_keys=provider_keys,
    )


def _merge_constraint_verdicts(
    verdict_lists: list[list[dict]],
    constraints: list[OracleConstraint],
) -> list[dict]:
    """Merge parallel judge verdicts with constraint-type-aware voting.

    expected=True  → LENIENT: matched=True if ANY judge says True
                     (don't penalise the model if one judge misses a satisfied check)
    expected=False → STRICT:  matched=True only if ALL judges say True
                     (don't falsely claim a failure is present due to one noisy judge)

    Reason: taken from first judge whose verdict agrees with the merged verdict.
    """
    n = len(constraints)
    result: list[dict] = []
    for i in range(n):
        items = [bl[i] for bl in verdict_lists if i < len(bl)]
        if not items:
            result.append({"verdict": False, "reason": None})
            continue
        votes = [item["verdict"] for item in items]
        if constraints[i].expected:
            merged_verdict = any(votes)   # LENIENT
        else:
            merged_verdict = all(votes)   # STRICT
        # Pick first reason from a judge that agrees with the merged verdict
        reason = next(
            (item["reason"] for item in items if item["verdict"] == merged_verdict and item.get("reason")),
            None,
        )
        result.append({"verdict": merged_verdict, "reason": reason})
    return result


def _merge_requirement_verdicts(
    results_per_dim: list[dict[str, list[bool] | None]],
    lengths: dict[str, int],
) -> dict[str, list[bool] | None]:
    """Merge per-judge requirement verdicts with dimension-aware voting.

    failure_modes → STRICT (all judges must agree failure is present)
    hidden / success / evaluation_criteria → LENIENT (any judge agreement = satisfied)
    """
    if not results_per_dim:
        return {k: None for k in lengths}
    if len(results_per_dim) == 1:
        return results_per_dim[0]

    merged: dict[str, list[bool] | None] = {}
    for dim, length in lengths.items():
        lists = [r[dim] for r in results_per_dim if r.get(dim) is not None]
        if not lists:
            merged[dim] = None
            continue
        if len(lists) == 1:
            merged[dim] = lists[0]
            continue
        result: list[bool] = []
        for i in range(length):
            votes = [bl[i] for bl in lists if i < len(bl)]
            if not votes:
                result.append(False)
                continue
            if dim == "failure_modes":
                result.append(all(votes))   # STRICT: only true if all agree failure present
            else:
                result.append(any(votes))   # LENIENT: true if any judge sees requirement met
        merged[dim] = result
    return merged


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def score_one(
    *,
    run_result: RunResult,
    oracle: TaskOracle,
    cfg: RunConfig,
    provider_keys: dict[str, str],
) -> ScoreResult:
    """Score a completed run against its oracle definition (LLM judge only)."""
    # Guard: empty output must score zero — no code produced = nothing to evaluate.
    code = (run_result.parsed_output.code or "").strip()
    if not code:
        LOGGER.warning("score_one: empty code output, returning zero score")
        zero_dim = ScoreDimension(matched=0, total=1, score=0.0, notes=["no code produced"])
        neutral = ScoreDimension(matched=0, total=0, score=1.0, notes=[])
        return ScoreResult(
            overall_score=0.0,
            passed=False,
            hidden_requirements=zero_dim,
            success_indicators=neutral,
            failure_modes=neutral,
            evaluation_criteria=neutral,
            constraint_scoring_used=False,
        )

    scoring_mode = (cfg.scoring_match_mode or "llm").lower()
    endpoint = (cfg.scoring_primary_endpoint or "auto").lower()

    constraints = _select_constraints(oracle, endpoint, cfg)

    if constraints:
        return _score_constraints(
            run_result=run_result,
            constraints=constraints,
            scoring_mode=scoring_mode,
            cfg=cfg,
            provider_keys=provider_keys,
        )

    return _score_legacy(
        run_result=run_result,
        oracle=oracle,
        scoring_mode=scoring_mode,
        cfg=cfg,
        provider_keys=provider_keys,
    )


# ---------------------------------------------------------------------------
# Constraint binary scoring
# ---------------------------------------------------------------------------


def _score_constraints(
    *,
    run_result: RunResult,
    constraints: list[OracleConstraint],
    scoring_mode: str,
    cfg: RunConfig,
    provider_keys: dict[str, str],
) -> ScoreResult:
    threshold = float(cfg.constraint_pass_threshold)

    llm_verdicts, judge_audit, judge_raw = _judge_constraints(
        run_result=run_result,
        constraints=constraints,
        cfg=cfg,
        provider_keys=provider_keys,
    )

    passed_count = 0
    misses: list[str] = []
    constraint_results: list[dict] = []

    for idx, constraint in enumerate(constraints):
        judged_item = (llm_verdicts[idx] if llm_verdicts is not None and idx < len(llm_verdicts) else None)
        # LLM verdict only — no lexical fallback.
        # False when judge is unavailable (no API key); surface this as a run error.
        verdict = bool(judged_item["verdict"]) if isinstance(judged_item, dict) else bool(judged_item)
        reason = judged_item.get("reason") if isinstance(judged_item, dict) else None

        satisfied = verdict if constraint.expected else not verdict
        if satisfied:
            passed_count += 1
        else:
            misses.append(constraint.id)

        constraint_results.append({
            "id": constraint.id,
            "passed": satisfied,
            "llm_verdict": verdict,
            "judge_reason": reason,
            "expected": constraint.expected,
            "voltsnip_key": constraint.voltsnip_key,
        })

    total = len(constraints)
    overall = round(passed_count / total, 4) if total > 0 else 1.0
    dim = ScoreDimension(matched=passed_count, total=total, score=overall, notes=[f"missing: {m}" for m in misses])
    neutral = ScoreDimension(matched=0, total=0, score=1.0, notes=[])

    def _slice_dim(prefix: str) -> ScoreDimension:
        # Filter the unified notes list for items that start with our prefix
        notes = [n for n in dim.notes if f"missing: {prefix}" in n]
        count = sum(1 for c in constraints if c.id.startswith(prefix))
        if count == 0:
            return ScoreDimension(matched=0, total=0, score=1.0, notes=[])
        failures = sum(1 for n in notes if "missing:" in n)
        # For inverted requirements (failures), matched = how many we successfully AVOIDED
        matched = count - failures
        score = round(matched / count, 4) if count > 0 else 1.0
        return ScoreDimension(matched=matched, total=count, score=score, notes=notes)

    if cfg.auto_constraints_from_legacy_oracle and any(c.id.startswith("auto_") for c in constraints):
        hidden_dim = _slice_dim("auto_hidden_")
        success_dim = _slice_dim("auto_success_")
        failure_dim = _slice_dim("auto_failure_INVERT_")
        criteria_dim = _slice_dim("auto_criteria_")
    else:
        hidden_dim = dim
        success_dim = dim
        failure_dim = dim
        criteria_dim = dim

    return ScoreResult(
        overall_score=overall,
        passed=overall >= threshold,
        hidden_requirements=hidden_dim,
        success_indicators=success_dim,
        failure_modes=failure_dim,
        evaluation_criteria=criteria_dim,
        evaluation_criteria_notes=[c.id for c in constraints],
        constraint_scoring_used=True,
        constraint_checks_passed=passed_count,
        constraint_checks_total=total,
        constraint_pass_threshold=threshold,
        constraint_results=constraint_results,
        judge_payload=judge_audit,
        judge_raw_response=judge_raw,
    )


def _judge_constraints(
    *,
    run_result: RunResult,
    constraints: list[OracleConstraint],
    cfg: RunConfig,
    provider_keys: dict[str, str],
) -> tuple[list[dict] | None, dict | None, str | None]:
    """Return (verdicts, judge_payload_audit, raw_response).

    verdicts: list of {"verdict": bool, "reason": str|None} — one entry per constraint, or None.
    judge_payload_audit: {"instructions": str, "user_json": str} — exact payload sent, for audit.
    raw_response: raw text from judge API — for reproducibility verification.
    """
    if not constraints:
        return None, None, None

    judge_specs = _parse_ensemble(cfg.scoring_judge_model)

    payload = {
        "candidate": {"code": run_result.parsed_output.code, "comments": run_result.parsed_output.comments},
        "constraints": [
            # NOTE: "expected" is intentionally omitted — leaking the expected verdict
            # to the judge anchors small models (e.g. gpt-5-mini) to copy it, corrupting
            # ~91% of expected=false verdicts due to format-example bias.
            {"id": c.id, "voltsnip_key": c.voltsnip_key, "check": c.check, "judge_prompt": c.judge_prompt}
            for c in constraints
        ],
    }
    # Select format example based on judge_prompt_variant (ablation study):
    #   "verdict-true"  → single true  example → anchors small models to always return true
    #   "verdict-false" → single false example → anchors small models to always return false
    #   "none"          → abstract <bool> placeholder, no concrete anchoring value
    #   "both"          → both true+false examples, corrected prompt (default)
    #   "pre-67f6ed0"   → exact old prompt before fix: single false example with verbose reason
    variant = getattr(cfg, "judge_prompt_variant", "both")
    if variant == "verdict-true":
        fmt_example = '{"results":[{"verdict":true,"reason":"..."},...]} '
    elif variant == "verdict-false":
        fmt_example = '{"results":[{"verdict":false,"reason":"..."},...]} '
    elif variant == "none":
        fmt_example = '{"results":[{"verdict":<bool>,"reason":"<explanation>"},...]} '
    elif variant == "pre-67f6ed0":
        fmt_example = '{"results":[{"verdict":false,"reason":"1-sentence explanation"},...]} '
    else:  # "both" (default)
        fmt_example = '{"results":[{"verdict":true,"reason":"..."},{"verdict":false,"reason":"..."},...]} '
    instructions = (
        "Judge each constraint independently as pass/fail for this candidate output. "
        "Use judge_prompt as the primary decision rule. "
        "Answer true if the described behavior IS present; false if it is NOT present. "
        f"Return ONLY JSON: {fmt_example}"
        "in the same order as input constraints. "
        "verdict must be a JSON boolean (true or false), not a string."
    )
    user_json = json.dumps(payload, ensure_ascii=False)
    audit = {"instructions": instructions, "user_json": user_json}

    # Filter to judges that have API keys available
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

    # Ensemble: call all judges in parallel
    verdict_lists: list[list[dict]] = []
    with ThreadPoolExecutor(max_workers=len(usable_specs)) as executor:
        first_raw: str | None = None
        futures = {
            executor.submit(_call_judge_raw, spec, instructions, user_json, cfg, provider_keys): spec
            for spec in usable_specs
        }
        for future in as_completed(futures):
            raw = future.result()
            if raw:
                if first_raw is None:
                    first_raw = raw
                parsed = _parse_json(raw)
                if parsed:
                    vl = _coerce_verdict_list(parsed.get("results"), len(constraints))
                    if vl is not None:
                        verdict_lists.append(vl)
                        LOGGER.debug(
                            "ensemble constraint judge=%s verdicts=%s",
                            futures[future],
                            [v["verdict"] for v in vl],
                        )

    if not verdict_lists:
        return None, audit, first_raw
    if len(verdict_lists) == 1:
        return verdict_lists[0], audit, first_raw

    # Merge ensemble results per constraint
    return _merge_constraint_verdicts(verdict_lists, constraints), audit, first_raw


# ---------------------------------------------------------------------------
# Legacy weighted scoring
# ---------------------------------------------------------------------------


def _score_legacy(
    *,
    run_result: RunResult,
    oracle: TaskOracle,
    scoring_mode: str,
    cfg: RunConfig,
    provider_keys: dict[str, str],
) -> ScoreResult:
    """Fallback when no constraints are defined."""
    llm_results = _judge_requirements(
        run_result=run_result,
        oracle=oracle,
        cfg=cfg,
        provider_keys=provider_keys,
    )

    def _dim(lines: list[str], llm_hits: list[bool] | None, *, invert: bool = False) -> ScoreDimension:
        if not lines:
            return ScoreDimension(matched=0, total=0, score=1.0, notes=[])
        hits, notes = 0, []
        for i, line in enumerate(lines):
            judged = (llm_hits[i] if llm_hits and i < len(llm_hits) else None)
            matched = bool(judged)   # LLM verdict only
            if invert:
                matched = not matched
            if matched:
                hits += 1
            else:
                notes.append(f"{'present (bad)' if invert else 'not found'}: {line[:60]}")
        score = round(hits / len(lines), 4)
        return ScoreDimension(matched=hits, total=len(lines), score=score, notes=notes)

    hidden_dim = _dim(oracle.hidden_requirements, llm_results.get("hidden"))
    success_dim = _dim(oracle.success_indicators.as_lines(), llm_results.get("success"))
    failure_dim_ = _dim(oracle.failure_modes, llm_results.get("failure_modes"), invert=True)
    criteria_dim = _dim(oracle.evaluation_criteria, llm_results.get("evaluation_criteria"))

    # Weighted overall: 40/30/20/10
    overall = round(
        0.40 * hidden_dim.score
        + 0.30 * success_dim.score
        + 0.20 * failure_dim_.score
        + 0.10 * criteria_dim.score,
        4,
    )
    return ScoreResult(
        overall_score=overall,
        passed=overall >= float(cfg.constraint_pass_threshold),
        hidden_requirements=hidden_dim,
        success_indicators=success_dim,
        failure_modes=failure_dim_,
        evaluation_criteria=criteria_dim,
        constraint_scoring_used=False,
    )


def _judge_requirements(
    *,
    run_result: RunResult,
    oracle: TaskOracle,
    cfg: RunConfig,
    provider_keys: dict[str, str],
) -> dict[str, list[bool] | None]:
    empty: dict[str, list[bool] | None] = {"hidden": None, "success": None, "failure_modes": None, "evaluation_criteria": None}

    judge_specs = _parse_ensemble(cfg.scoring_judge_model)
    usable_specs = [s for s in judge_specs if _judge_has_key(s, cfg, provider_keys)]
    if not usable_specs:
        return empty

    hidden = oracle.hidden_requirements
    success = oracle.success_indicators.as_lines()
    failures = oracle.failure_modes
    criteria = oracle.evaluation_criteria

    payload = {
        "candidate": {"code": run_result.parsed_output.code, "comments": run_result.parsed_output.comments},
        "requirements": {"hidden": hidden, "success": success, "failure_modes": failures, "evaluation_criteria": criteria},
    }
    instructions = (
        "Evaluate whether each requirement is satisfied by the candidate code/comments. "
        "For failure_modes, mark true only when the failure behavior is actually present. "
        "Return ONLY JSON with arrays of booleans: hidden, success, failure_modes, evaluation_criteria."
    )
    user_json = json.dumps(payload, ensure_ascii=False)
    lengths = {"hidden": len(hidden), "success": len(success), "failure_modes": len(failures), "evaluation_criteria": len(criteria)}

    def _parse_one(raw: str | None) -> dict[str, list[bool] | None] | None:
        if not raw:
            return None
        parsed = _parse_json(raw)
        if parsed is None:
            return None
        return {
            "hidden": _coerce_bool_list(parsed.get("hidden"), len(hidden)),
            "success": _coerce_bool_list(parsed.get("success"), len(success)),
            "failure_modes": _coerce_bool_list(parsed.get("failure_modes"), len(failures)),
            "evaluation_criteria": _coerce_bool_list(parsed.get("evaluation_criteria"), len(criteria)),
        }

    if len(usable_specs) == 1:
        result = _parse_one(_call_judge_raw(usable_specs[0], instructions, user_json, cfg, provider_keys))
        return result if result is not None else empty

    # Ensemble: call all judges in parallel
    results_per_judge: list[dict[str, list[bool] | None]] = []
    with ThreadPoolExecutor(max_workers=len(usable_specs)) as executor:
        futures = {
            executor.submit(_call_judge_raw, spec, instructions, user_json, cfg, provider_keys): spec
            for spec in usable_specs
        }
        for future in as_completed(futures):
            result = _parse_one(future.result())
            if result is not None:
                results_per_judge.append(result)
                LOGGER.debug("ensemble requirement judge=%s done", futures[future])

    if not results_per_judge:
        return empty
    return _merge_requirement_verdicts(results_per_judge, lengths)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _select_constraints(
    oracle: TaskOracle,
    endpoint: str,
    cfg: RunConfig,
) -> list[OracleConstraint]:
    if endpoint == "legacy_weighted":
        return []
    if endpoint == "constraint_binary" and oracle.constraints:
        return oracle.constraints
    if endpoint == "auto":
        if oracle.constraints:
            return oracle.constraints
        if cfg.auto_constraints_from_legacy_oracle:
            return _synthetic_constraints(oracle)
    return []


def _synthetic_constraints(oracle: TaskOracle) -> list[OracleConstraint]:
    """Synthesize binary constraints from legacy oracle dimensions when no explicit constraints exist."""
    constraints: list[OracleConstraint] = []
    
    def _add_set(items: list[str], prefix: str, prompt_template: str) -> None:
        for i, item in enumerate(items):
            item = item.strip()
            if not item:
                continue
            constraints.append(OracleConstraint(
                id=f"{prefix}_{i}",
                check=item,
                judge_prompt=prompt_template.format(item=item),
            ))

    _add_set(oracle.hidden_requirements, "auto_hidden", "Does the implementation satisfy: {item}")
    _add_set(oracle.success_indicators.as_lines(), "auto_success", "Does the implementation include: {item}")
    # For failures, we want the LLM to return FALSE if the failure behavior is present (meaning it failed the constraint)
    # The runner prompts check "Does the implementation exhibit..." and we will invert the boolean later.
    def _add_failure_set(items: list[str], prefix: str, prompt_template: str) -> None:
        for i, item in enumerate(items):
            item = item.strip()
            if not item:
                continue
            constraints.append(OracleConstraint(
                id=f"{prefix}_{i}",
                check=item,
                judge_prompt=prompt_template.format(item=item),
                expected=False,
            ))
    _add_failure_set(oracle.failure_modes, "auto_failure_INVERT", "Does the implementation exhibit this failure mode: {item}")
    _add_set(oracle.evaluation_criteria, "auto_criteria", "Does the implementation satisfy this criteria: {item}")
    
    return constraints




def _has_key(provider: str, cfg: RunConfig, provider_keys: dict[str, str]) -> bool:
    import os
    if cfg.api_key:
        return True
    if provider in cfg.provider_api_keys:
        return True
    if provider in provider_keys:
        return True
    env_map = {"openai": "OPENAI_API_KEY", "anthropic": "ANTHROPIC_API_KEY"}
    env_k = env_map.get(provider)
    return bool(env_k and os.environ.get(env_k))


def _judge_has_key(judge_model: str, cfg: RunConfig, provider_keys: dict[str, str]) -> bool:
    """Return True if the judge model's provider has a usable credential."""
    provider = judge_model.split(":")[0].lower() if ":" in judge_model else "openai"
    # subprocess providers use stored CLI auth — always available
    if provider in ("claudecode", "codex", "mock"):
        return True
    # API providers require a key
    return _has_key(provider, cfg, provider_keys)


def _parse_json(text: str) -> dict[str, Any] | None:
    text = text.strip()
    try:
        obj = json.loads(text)
        return obj if isinstance(obj, dict) else None
    except Exception:
        pass
    # Scan for first JSON object
    depth = 0
    start = None
    in_str = False
    escaped = False
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
    if len(result) < expected_len:
        result.extend([False] * (expected_len - len(result)))
    return result[:expected_len]


def _coerce_verdict_list(raw: Any, expected_len: int) -> list[dict] | None:
    """Parse judge output into list of {"verdict": bool, "reason": str|None}.

    Handles both the new rich format  [{"verdict": true, "reason": "…"}, ...]
    and the legacy bare-boolean format [true, false, ...] for backward compat.
    """
    if not isinstance(raw, list):
        return None
    result: list[dict] = []
    for v in raw:
        if isinstance(v, dict):
            verdict = bool(v.get("verdict", False))
            reason_raw = v.get("reason")
            reason = str(reason_raw).strip() if reason_raw else None
        elif isinstance(v, (bool, int)):
            verdict = bool(v)
            reason = None
        else:
            verdict = False
            reason = None
        result.append({"verdict": verdict, "reason": reason})
    while len(result) < expected_len:
        result.append({"verdict": False, "reason": None})
    return result[:expected_len]
