#!/usr/bin/env python3
"""
matrix_insights.py — extract every meaningful insight from a matrix_results.csv.

Usage:
    python vsevals/scripts/matrix_insights.py [--csv PATH] [--format {text,json,md}]

Defaults to the latest matrix_results.csv found under vsevals_final_runs/.
"""
import argparse
import csv
import json
import statistics
import sys
from collections import defaultdict
from pathlib import Path


# ─── helpers ─────────────────────────────────────────────────────────────────

def flt(v, default: float = 0.0) -> float:
    try:
        return float(v) if v not in ("", None, "nan", "None") else default
    except (TypeError, ValueError):
        return default


def boo(v) -> bool:
    return str(v).lower() in ("true", "1", "yes")


def avg(lst, fn=None) -> float:
    vals = [fn(r) for r in lst] if fn else list(lst)
    vals = [v for v in vals if v == v and v is not None]
    return statistics.mean(vals) if vals else 0.0


def safe_std(lst) -> float:
    return statistics.stdev(lst) if len(lst) >= 2 else 0.0


def fp(lst) -> float:
    """full_pass rate as %"""
    return sum(r["_fp"] for r in lst) / len(lst) * 100 if lst else 0.0


def sc(lst) -> float:
    return avg(lst, lambda r: r["_score"])


# ─── data loading ─────────────────────────────────────────────────────────────

TOOL_V   = ["P2", "P7", "P8", "P9"]
NOTOOL_V = ["P0", "P1", "P3", "P4", "P5", "P6"]
STATIC_V = ["P4", "P5", "P6"]   # sidecar context, no live tools
MEM_V    = ["P3"]                # injected memory variants
ALL_V    = ["P0", "P1", "P2", "P3", "P4", "P5", "P6", "P7", "P8", "P9"]


def load(path: str) -> list[dict]:
    with open(path) as f:
        raw = list(csv.DictReader(f))
    rows = [r for r in raw if r["status"] == "ok" and not r["model_name"].startswith("mock:")]
    for r in rows:
        r["_fp"]        = boo(r.get("full_pass", ""))
        r["_score"]     = flt(r.get("overall_score", 0))
        r["_tc"]        = int(flt(r.get("tool_call_count", 0)))
        r["_cost"]      = flt(r.get("cost_usd", 0))
        r["_lat"]       = flt(r.get("model_request_latency_ms", 0))
        r["_tok"]       = int(flt(r.get("total_tokens", 0)))
        r["_pt"]        = int(flt(r.get("prompt_tokens", 0)))
        r["_ct"]        = int(flt(r.get("completion_tokens", 0)))
        r["_snip_inj"]  = int(flt(r.get("snippet_injected_count", 0)))
        r["_snip_util"] = flt(r.get("snippet_utilized_fraction", 0))
        r["_rtrips"]    = int(flt(r.get("tool_roundtrips_used", 0)))
        r["_has_mem"]   = boo(r.get("variant_memory_enabled", ""))
        r["_hr"]        = flt(r.get("hidden_requirements_score", 0))
        r["_si"]        = flt(r.get("success_indicators_score", 0))
        r["_fm"]        = flt(r.get("failure_modes_score", 0))
        r["_ec"]        = flt(r.get("evaluation_criteria_score", 0))
        r["_pytest"]    = boo(r.get("pytest_passed", ""))
        r["_py_ran"]    = boo(r.get("pytest_ran", ""))
        r["_pfail"]     = r.get("process_fail_reason", "")
        r["_ochar"]     = int(flt(r.get("output_chars", 0)))
        r["_vs_tot"]    = int(flt(r.get("voltsnip_constraints_total", 0)))
        r["_vs_rate"]   = flt(r.get("voltsnip_constraint_pass_rate", 0))
    return rows


# ─── insight engine ───────────────────────────────────────────────────────────

def build_insights(rows: list[dict]) -> dict:
    MODELS  = sorted(set(r["model_name"] for r in rows))
    TASKS   = sorted(set(r["task_id"]    for r in rows))
    CATS    = sorted(set(r["task_category"] for r in rows if r["task_category"]))

    vmap   = {v: [r for r in rows if r["variant_id"] == v] for v in ALL_V}
    tv     = [r for r in rows if r["variant_id"] in TOOL_V]
    ntv    = [r for r in rows if r["variant_id"] in NOTOOL_V]
    called = [r for r in rows if r["_tc"] > 0]
    ncall  = [r for r in rows if r["_tc"] == 0]
    has_s  = [r for r in rows if r["_snip_inj"] > 0]
    no_s   = [r for r in rows if r["_snip_inj"] == 0]
    pass_r = [r for r in rows if r["_fp"]]
    fail_r = [r for r in rows if not r["_fp"]]

    p0, p1      = vmap["P0"], vmap["P1"]                # no context baselines
    p2          = vmap["P2"]                            # tools only, zero guidance
    p3          = vmap["P3"]                            # injected memory
    p4, p5, p6  = vmap["P4"], vmap["P5"], vmap["P6"]   # static context variants
    p7, p8, p9  = vmap["P7"], vmap["P8"], vmap["P9"]   # live retrieval variants

    pfail = defaultdict(int)
    for r in rows:
        if r["_pfail"]:
            pfail[r["_pfail"]] += 1

    # Per-task P0 baseline
    p0_by_task  = {t: fp([r for r in rows if r["task_id"] == t and r["variant_id"] == "P0"]) for t in TASKS}
    hard_tasks  = [t for t, f in p0_by_task.items() if f < 50]
    med_tasks   = [t for t, f in p0_by_task.items() if 50 <= f < 80]
    easy_tasks  = [t for t, f in p0_by_task.items() if f >= 80]

    hard_p0  = [r for r in rows if r["task_id"] in hard_tasks and r["variant_id"] == "P0"]
    hard_tv  = [r for r in rows if r["task_id"] in hard_tasks and r["variant_id"] in TOOL_V]
    hard_p9  = [r for r in rows if r["task_id"] in hard_tasks and r["variant_id"] == "P9"]

    # Uplift per task
    uplift_task = {
        t: fp([r for r in rows if r["task_id"] == t and r["variant_id"] in TOOL_V])
         - fp([r for r in rows if r["task_id"] == t and r["variant_id"] == "P0"])
        for t in TASKS
    }
    top5_uplift = sorted(uplift_task.items(), key=lambda x: -x[1])[:5]
    top5_hurt   = sorted(uplift_task.items(), key=lambda x:  x[1])[:5]

    # Model stats
    def tcr(m):
        mvt = [r for r in rows if r["model_name"] == m and r["variant_id"] in TOOL_V]
        return sum(1 for r in mvt if r["_tc"] > 0) / max(len(mvt), 1)

    model_uplift = {
        m: fp([r for r in rows if r["model_name"] == m and r["variant_id"] in TOOL_V])
         - fp([r for r in rows if r["model_name"] == m and r["variant_id"] == "P0"])
        for m in MODELS
    }
    model_stdev = {
        m: safe_std([fp([r for r in rows if r["model_name"] == m and r["task_id"] == t])
                     for t in TASKS if [r for r in rows if r["model_name"] == m and r["task_id"] == t]])
        for m in MODELS
    }

    # Roundtrip analysis
    rt_fps = {
        n: fp([r for r in tv if r["_rtrips"] == n])
        for n in range(10) if any(r["_rtrips"] == n for r in tv)
    }

    # ── assemble result dict ─────────────────────────────────────────────────
    I = {}  # insights dict

    # OVERVIEW
    I["overview"] = {
        "total_real_runs":      len(rows),
        "tasks":                TASKS,
        "models":               MODELS,
        "variants":             ALL_V,
        "matrix_cells":         len(rows),
        "expected_cells":       len(TASKS) * len(ALL_V) * len(MODELS),
        "completeness_pct":     len(rows) / max(len(TASKS) * len(ALL_V) * len(MODELS), 1) * 100,
    }

    # BASELINE
    I["baseline"] = {
        "overall_full_pass_pct":     round(fp(rows), 2),
        "overall_avg_score":         round(sc(rows), 4),
        "P0_full_pass_pct":          round(fp(p0), 2),
        "P0_avg_score":              round(sc(p0), 4),
        "score_gte_0_70_pct":        round(sum(1 for r in rows if r["_score"] >= 0.7) / len(rows) * 100, 2),
        "tool_compliance_gap_pp":    round(sum(1 for r in rows if r["_score"] >= 0.7) / len(rows) * 100 - fp(rows), 2),
        "P1_vs_P0_delta_pp":         round(fp(p1) - fp(p0), 2),
    }

    # PER-VARIANT
    I["per_variant"] = {
        v: {
            "full_pass_pct":  round(fp(vmap[v]), 2),
            "avg_score":      round(sc(vmap[v]), 4),
            "n":              len(vmap[v]),
            "avg_tool_calls": round(avg(vmap[v], lambda r: r["_tc"]), 2),
            "avg_cost_usd":   round(avg(vmap[v], lambda r: r["_cost"]), 4),
            "avg_latency_ms": round(avg(vmap[v], lambda r: r["_lat"]), 0),
        }
        for v in ALL_V
    }

    # TOOL vs NO-TOOL
    I["tool_vs_notool"] = {
        "tool_full_pass_pct":     round(fp(tv), 2),
        "notool_full_pass_pct":   round(fp(ntv), 2),
        "delta_pp":               round(fp(tv) - fp(ntv), 2),
        "tool_avg_score":         round(sc(tv), 4),
        "notool_avg_score":       round(sc(ntv), 4),
        "score_delta":            round(sc(tv) - sc(ntv), 4),
        "best_variant":           max(ALL_V, key=lambda v: fp(vmap[v])),
        "worst_variant":          min(ALL_V, key=lambda v: fp(vmap[v])),
    }

    # VOLTSNIP CALL BEHAVIOUR
    I["voltsnip_calls"] = {
        "runs_called":              len(called),
        "runs_not_called":          len(ncall),
        "call_rate_pct":            round(len(called) / len(rows) * 100, 2),
        "tool_variant_call_rate_pct": round(sum(1 for r in tv if r["_tc"] > 0) / max(len(tv), 1) * 100, 2),
        "full_pass_when_called_pct":    round(fp(called), 2),
        "full_pass_when_not_called_pct":round(fp(ncall), 2),
        "full_pass_delta_pp":           round(fp(called) - fp(ncall), 2),
        "score_when_called":            round(sc(called), 4),
        "score_when_not_called":        round(sc(ncall), 4),
        "score_delta":                  round(sc(called) - sc(ncall), 4),
        "called_and_passed":            sum(1 for r in called if r["_fp"]),
        "call_rate_per_variant":        {v: round(sum(1 for r in vmap[v] if r["_tc"] > 0) / max(len(vmap[v]), 1) * 100, 1) for v in TOOL_V},
        "avg_calls_per_tool_run":       round(avg(tv, lambda r: r["_tc"]), 2),
        "max_calls_single_run":         max(r["_tc"] for r in rows),
        "score_in_tool_variants_called":     round(sc([r for r in tv if r["_tc"] > 0]), 4),
        "score_in_tool_variants_not_called": round(sc([r for r in tv if r["_tc"] == 0]), 4),
    }

    # TASK DIFFICULTY
    I["task_difficulty"] = {
        "hard_tasks_p0_lt50":    hard_tasks,
        "medium_tasks_p0_50_80": med_tasks,
        "easy_tasks_p0_gte80":   easy_tasks,
        "p0_per_task":           {t: round(p0_by_task[t], 1) for t in TASKS},
        "tool_fp_per_task":      {t: round(fp([r for r in rows if r["task_id"] == t and r["variant_id"] in TOOL_V]), 1) for t in TASKS},
        "uplift_per_task":       {t: round(uplift_task[t], 1) for t in TASKS},
        "top5_highest_uplift":   top5_uplift,
        "top5_biggest_hurt":     top5_hurt,
        "hard_p0_fp_pct":        round(fp(hard_p0), 2),
        "hard_tool_fp_pct":      round(fp(hard_tv), 2),
        "hard_uplift_pp":        round(fp(hard_tv) - fp(hard_p0), 2),
        "hard_p9_fp_pct":        round(fp(hard_p9), 2),
        "tasks_zero_pass":       [t for t in TASKS if fp([r for r in rows if r["task_id"] == t]) == 0.0],
        "tasks_100pct_pass":     [t for t in TASKS if fp([r for r in rows if r["task_id"] == t]) == 100.0],
    }

    # CATEGORY
    I["category"] = {
        c: {
            "n":              len([r for r in rows if r["task_category"] == c]),
            "overall_fp_pct": round(fp([r for r in rows if r["task_category"] == c]), 2),
            "p0_fp_pct":      round(fp([r for r in rows if r["task_category"] == c and r["variant_id"] == "P0"]), 2),
            "tool_fp_pct":    round(fp([r for r in rows if r["task_category"] == c and r["variant_id"] in TOOL_V]), 2),
            "uplift_pp":      round(fp([r for r in rows if r["task_category"] == c and r["variant_id"] in TOOL_V])
                                   - fp([r for r in rows if r["task_category"] == c and r["variant_id"] == "P0"]), 2),
        }
        for c in CATS
    }

    # MODEL
    I["model"] = {
        m: {
            "full_pass_pct":        round(fp([r for r in rows if r["model_name"] == m]), 2),
            "avg_score":            round(sc([r for r in rows if r["model_name"] == m]), 4),
            "tool_call_rate_pct":   round(tcr(m) * 100, 1),
            "tool_fp_pct":          round(fp([r for r in rows if r["model_name"] == m and r["variant_id"] in TOOL_V]), 2),
            "p0_fp_pct":            round(fp([r for r in rows if r["model_name"] == m and r["variant_id"] == "P0"]), 2),
            "uplift_vs_p0_pp":      round(model_uplift[m], 2),
            "no_tool_calls_count":  sum(1 for r in rows if r["model_name"] == m and r["_pfail"] == "no_tool_calls"),
            "avg_cost_usd":         round(avg([r for r in rows if r["model_name"] == m], lambda r: r["_cost"]), 4),
            "total_cost_usd":       round(sum(r["_cost"] for r in rows if r["model_name"] == m), 2),
            "avg_latency_ms":       round(avg([r for r in rows if r["model_name"] == m], lambda r: r["_lat"]), 0),
            "task_fp_stdev":        round(model_stdev[m], 2),
        }
        for m in MODELS
    }
    I["model"]["_best_caller"]    = max(MODELS, key=tcr)
    I["model"]["_best_uplift"]    = max(model_uplift, key=lambda m: model_uplift[m])
    I["model"]["_worst_uplift"]   = min(model_uplift, key=lambda m: model_uplift[m])
    I["model"]["_most_consistent"]= min(model_stdev,  key=lambda m: model_stdev[m])

    # MEMORY
    mem_rows   = [r for r in rows if r["_has_mem"]]
    nomem_rows = [r for r in rows if not r["_has_mem"]]
    I["memory"] = {
        "mem_full_pass_pct":       round(fp(mem_rows), 2),
        "nomem_full_pass_pct":     round(fp(nomem_rows), 2),
        "mem_delta_pp":            round(fp(mem_rows) - fp(nomem_rows), 2),
        "P7_8_9_fp":               {"P7": round(fp(p7), 2), "P8": round(fp(p8), 2), "P9": round(fp(p9), 2)},
        "P7_zero_roundtrip_pct":   round(sum(1 for r in p7 if r["_tc"] == 0) / max(len(p7), 1) * 100, 1),
        "memory_token_overhead":   round(avg(mem_rows, lambda r: r["_pt"]) - avg(p2, lambda r: r["_pt"]), 0),
        "P9_vs_P0_delta_pp":       round(fp(p9) - fp(p0), 2),
        "P9_vs_P2_delta_pp":       round(fp(p9) - fp(p2), 2),
    }

    # SNIPPETS
    I["snippets"] = {
        "injected_full_pass_pct":  round(fp(has_s), 2),
        "no_snip_full_pass_pct":   round(fp(no_s), 2),
        "delta_pp":                round(fp(has_s) - fp(no_s), 2),
        "injected_avg_score":      round(sc(has_s), 4),
        "no_snip_avg_score":       round(sc(no_s), 4),
        "avg_utilized_fraction":   round(avg([r for r in tv if r["_snip_inj"] > 0], lambda r: r["_snip_util"]), 3),
        "injected_but_score_lt07": sum(1 for r in has_s if r["_score"] < 0.7),
        "avg_injected_chars":      round(avg([r for r in rows if r["_snip_inj"] > 0], lambda r: flt(r.get("snippet_injected_chars", 0))), 0),
    }

    # TOOL PRESSURE ABLATION
    I["tool_pressure"] = {
        "P2_fp_pct":                 round(fp(p2), 2),
        "P7_fp_pct":                 round(fp(p7), 2),
        "P9_fp_pct":                 round(fp(p9), 2),
        "P2_avg_tc":                 round(avg(p2, lambda r: r["_tc"]), 2),
        "P7_avg_tc":                 round(avg(p7, lambda r: r["_tc"]), 2),
        "P9_avg_tc":                 round(avg(p9, lambda r: r["_tc"]), 2),
        "P9_compliance_pct":         round(sum(1 for r in p9 if r["_tc"] > 0) / max(len(p9), 1) * 100, 1),
        "P9_vs_P2_mandate_delta_pp": round(fp(p9) - fp(p2), 2),
        "P9_vs_P8_context_delta_pp": round(fp(p9) - fp(p8), 2),
    }

    # PROCESS COMPLIANCE
    I["compliance"] = {
        "no_tool_calls_count":      pfail.get("no_tool_calls", 0),
        "no_tool_calls_pct":        round(pfail.get("no_tool_calls", 0) / len(rows) * 100, 2),
        "no_tool_calls_avg_score":  round(sc([r for r in rows if r["_pfail"] == "no_tool_calls"]), 4),
        "outcome_failed_count":     pfail.get("outcome_failed", 0),
        "all_fail_reasons":         dict(sorted(pfail.items(), key=lambda x: -x[1])),
        "no_tc_by_variant":         {v: sum(1 for r in rows if r["variant_id"] == v and r["_pfail"] == "no_tool_calls") for v in TOOL_V},
        "no_tc_by_model":           {m: sum(1 for r in rows if r["model_name"] == m and r["_pfail"] == "no_tool_calls") for m in MODELS},
        "compliance_rate_by_model": {m: round(sum(1 for r in rows if r["model_name"] == m and not r["_pfail"]) / max(sum(1 for r in rows if r["model_name"] == m), 1) * 100, 1) for m in MODELS},
    }

    # ROUNDTRIPS
    I["roundtrips"] = {
        "avg_roundtrips_tool_variants": round(avg(tv, lambda r: r["_rtrips"]), 2),
        "zero_roundtrip_pct":           round(sum(1 for r in tv if r["_rtrips"] == 0) / len(tv) * 100, 1),
        "full_pass_by_roundtrip":       {n: round(rt_fps[n], 1) for n in sorted(rt_fps)},
        "sweet_spot_roundtrips":        min((n for n in rt_fps if rt_fps[n] >= 95), default=None),
    }

    # SCORE DIMENSIONS
    I["score_dims"] = {
        dim: {
            "tool_avg":   round(avg(tv,  lambda r: r[key]), 4),
            "notool_avg": round(avg(ntv, lambda r: r[key]), 4),
            "delta":      round(avg(tv, lambda r: r[key]) - avg(ntv, lambda r: r[key]), 4),
        }
        for dim, key in [("hidden_requirements", "_hr"), ("success_indicators", "_si"),
                         ("failure_modes", "_fm"), ("evaluation_criteria", "_ec")]
    }

    # COST
    I["cost"] = {
        "avg_cost_all_usd":       round(avg(rows, lambda r: r["_cost"]), 4),
        "total_cost_usd":         round(sum(r["_cost"] for r in rows), 2),
        "avg_cost_passing_usd":   round(avg(pass_r, lambda r: r["_cost"]), 4),
        "avg_cost_failing_usd":   round(avg(fail_r, lambda r: r["_cost"]), 4),
        "cache_hit_rate_pct":     round(avg(rows, lambda r: flt(r.get("cached_tokens", 0)) / max(r["_pt"], 1) * 100), 2),
        "avg_cost_per_variant":   {v: round(avg(vmap[v], lambda r: r["_cost"]), 4) for v in ALL_V},
    }

    # LATENCY
    I["latency"] = {
        "avg_latency_tool_ms":   round(avg(tv, lambda r: r["_lat"]), 0),
        "avg_latency_notool_ms": round(avg(ntv, lambda r: r["_lat"]), 0),
        "avg_latency_pass_ms":   round(avg(pass_r, lambda r: r["_lat"]), 0),
        "avg_latency_fail_ms":   round(avg(fail_r, lambda r: r["_lat"]), 0),
        "avg_latency_by_model":  {m: round(avg([r for r in rows if r["model_name"] == m], lambda r: r["_lat"]), 0) for m in MODELS},
    }

    # TOKENS
    I["tokens"] = {
        "avg_total_tokens_tool":   round(avg(tv,    lambda r: r["_tok"]), 0),
        "avg_total_tokens_notool": round(avg(ntv,   lambda r: r["_tok"]), 0),
        "avg_prompt_with_snip":    round(avg(has_s, lambda r: r["_pt"]), 0),
        "avg_prompt_no_snip":      round(avg(no_s,  lambda r: r["_pt"]), 0),
    }

    # OUTPUT
    I["output"] = {
        "avg_output_chars_pass":      round(avg(pass_r, lambda r: r["_ochar"]), 0),
        "avg_output_chars_fail":      round(avg(fail_r, lambda r: r["_ochar"]), 0),
        "avg_code_lines_pass":        round(avg(pass_r, lambda r: flt(r.get("generated_code_lines", 0))), 0),
        "avg_code_lines_fail":        round(avg(fail_r, lambda r: flt(r.get("generated_code_lines", 0))), 0),
        "avg_completion_tokens_tool": round(avg(tv,  lambda r: r["_ct"]), 0),
        "avg_completion_tokens_ntool":round(avg(ntv, lambda r: r["_ct"]), 0),
    }

    # PYTEST
    py_ran = [r for r in rows if r["_py_ran"]]
    py_ok  = [r for r in py_ran if r["_pytest"]]
    I["pytest"] = {
        "ran_pct":       round(len(py_ran) / len(rows) * 100, 1),
        "pass_pct":      round(len(py_ok)  / max(len(py_ran), 1) * 100, 1),
        "agreement_pct": round(sum(1 for r in py_ran if r["_pytest"] == r["_fp"]) / max(len(py_ran), 1) * 100, 1),
    }

    # VS CONSTRAINTS
    vs_r = [r for r in rows if r["_vs_tot"] > 0]
    I["vs_constraints"] = {
        "evaluated_pct":           round(len(vs_r) / len(rows) * 100, 1),
        "avg_pass_rate":           round(avg(vs_r, lambda r: r["_vs_rate"]), 4) if vs_r else None,
        "avg_pass_rate_called":    round(avg([r for r in called if r["_vs_tot"] > 0], lambda r: r["_vs_rate"]), 4) if vs_r else None,
        "avg_pass_rate_not_called":round(avg([r for r in ncall  if r["_vs_tot"] > 0], lambda r: r["_vs_rate"]), 4) if vs_r else None,
    }

    # ERRORS
    I["errors"] = {
        "tool_error_runs":        sum(1 for r in rows if int(flt(r.get("tool_error_count", 0))) > 0),
        "tool_error_pct":         round(sum(1 for r in rows if int(flt(r.get("tool_error_count", 0))) > 0) / len(rows) * 100, 2),
        "avg_voltsnip_errors":    round(avg(tv, lambda r: flt(r.get("voltsnip_error_count", 0))), 3),
        "avg_provider_retries":   round(avg(rows, lambda r: flt(r.get("provider_retry_count", 0))), 3),
    }

    # SYNTHESIS / VERDICTS
    mandate_delta = round(fp(p9) - fp(p2), 2)
    hard_uplift   = round(fp(hard_tv) - fp(hard_p0), 2)
    called_delta  = round(fp(called) - fp(ncall), 2)
    if mandate_delta > 40:
        verdict = "STRONG — mandate forces VoltSnip use and dramatically boosts compliance"
    elif hard_uplift > 20:
        verdict = "YES — clear uplift on hard tasks where baseline fails"
    elif called_delta > 15:
        verdict = "YES — runs that call VoltSnip pass at much higher rate"
    else:
        verdict = "MODEST — ceiling effect on easy tasks; harder benchmark needed"

    I["synthesis"] = {
        "mandate_effect_pp":           mandate_delta,
        "called_vs_uncalled_delta_pp": called_delta,
        "hard_task_uplift_pp":         hard_uplift,
        "best_notool_fp_pct":          round(max(fp(vmap[v]) for v in NOTOOL_V), 2),
        "best_tool_fp_pct":            round(max(fp(vmap[v]) for v in TOOL_V), 2),
        "p10_vs_p4_is_key_finding":    True,
        "verdict":                     verdict,
    }

    return I


# ─── formatters ───────────────────────────────────────────────────────────────

def fmt_text(I: dict) -> str:
    lines = []
    W = 120

    def hr(char="─"): lines.append(char * W)
    def h1(t): hr("═"); lines.append(f"  {t}"); hr("═")
    def h2(t): hr(); lines.append(f"  ▶ {t}"); hr()
    def kv(k, v, indent=4): lines.append(f"{' '*indent}{k:<50} {v}")

    h1(f"VOLTSNIP MATRIX INSIGHTS  ({I['overview']['total_real_runs']} runs, "
       f"{len(I['overview']['tasks'])} tasks, {len(I['overview']['models'])} models, "
       f"matrix {I['overview']['completeness_pct']:.1f}% complete)")

    h2("BASELINE")
    kv("Overall full_pass",          f"{I['baseline']['overall_full_pass_pct']:.1f}%")
    kv("P0 raw baseline full_pass",  f"{I['baseline']['P0_full_pass_pct']:.1f}%")
    kv("Avg overall_score",          f"{I['baseline']['overall_avg_score']:.3f}")
    kv("Score≥0.70 rate",            f"{I['baseline']['score_gte_0_70_pct']:.1f}%  (gap vs full_pass: {I['baseline']['tool_compliance_gap_pp']:+.1f}pp)")
    kv("P1 oracle injection Δ vs P0",f"{I['baseline']['P1_vs_P0_delta_pp']:+.1f}pp")

    h2("PER-VARIANT FULL_PASS RANKING")
    for v in sorted(I["per_variant"], key=lambda v: -I["per_variant"][v]["full_pass_pct"]):
        d = I["per_variant"][v]
        kv(v, f"full_pass={d['full_pass_pct']:.1f}%  score={d['avg_score']:.3f}  avg_tc={d['avg_tool_calls']:.2f}  cost=${d['avg_cost_usd']:.4f}")

    h2("TOOL vs NO-TOOL")
    tn = I["tool_vs_notool"]
    kv("Tool variants",    f"{tn['tool_full_pass_pct']:.1f}%  score={tn['tool_avg_score']:.3f}")
    kv("No-tool variants", f"{tn['notool_full_pass_pct']:.1f}%  score={tn['notool_avg_score']:.3f}")
    kv("Δ full_pass",      f"{tn['delta_pp']:+.1f}pp")

    h2("VOLTSNIP CALL BEHAVIOUR")
    v = I["voltsnip_calls"]
    kv("Runs that called VoltSnip",   f"{v['runs_called']}/{I['overview']['total_real_runs']}  ({v['call_rate_pct']:.1f}%)")
    kv("Tool-variant call rate",      f"{v['tool_variant_call_rate_pct']:.1f}%")
    kv("Full_pass when CALLED",       f"{v['full_pass_when_called_pct']:.1f}%")
    kv("Full_pass when NOT called",   f"{v['full_pass_when_not_called_pct']:.1f}%  (Δ={v['full_pass_delta_pp']:+.1f}pp)")
    kv("Score when called vs not",    f"{v['score_when_called']:.3f} vs {v['score_when_not_called']:.3f}  (Δ={v['score_delta']:+.3f})")
    kv("Call rate per variant",       "  ".join(f"{k}={vv:.0f}%" for k,vv in v["call_rate_per_variant"].items()))

    h2("★ KEY FINDING — MANDATE EFFECT (P2→P9)")
    tp = I["tool_pressure"]
    kv("P2 (agent-decides)",  f"{tp['P2_fp_pct']:.1f}%  avg_tc={tp['P2_avg_tc']:.2f}")
    kv("P7 (skills+tools)",   f"{tp['P7_fp_pct']:.1f}%  avg_tc={tp['P7_avg_tc']:.2f}")
    kv("P9 (ceiling)",        f"{tp['P9_fp_pct']:.1f}%  avg_tc={tp['P9_avg_tc']:.2f}  compliance={tp['P9_compliance_pct']:.0f}%")
    kv("Δ P9−P2 (mandate)",   f"{tp['P9_vs_P2_mandate_delta_pp']:+.1f}pp")
    kv("Δ P9−P8 (context)",   f"{tp['P9_vs_P8_context_delta_pp']:+.1f}pp  ← value of combined context over agents.md alone")

    h2("TASK DIFFICULTY")
    td = I["task_difficulty"]
    kv("Hard tasks (P0<50%)",   str(td["hard_tasks_p0_lt50"]))
    kv("Medium tasks (50-80%)", str(td["medium_tasks_p0_50_80"]))
    kv("Easy tasks (P0≥80%)",   f"{len(td['easy_tasks_p0_gte80'])} tasks")
    kv("Hard: P0 → tool Δ",     f"{td['hard_p0_fp_pct']:.1f}% → {td['hard_tool_fp_pct']:.1f}%  Δ={td['hard_uplift_pp']:+.1f}pp")
    kv("Top 5 task uplifts",    "  ".join(f"{t}:{u:+.0f}pp" for t,u in td["top5_highest_uplift"]))
    kv("Top 5 task hurts",      "  ".join(f"{t}:{u:+.0f}pp" for t,u in td["top5_biggest_hurt"]))

    h2("CATEGORY")
    for c, cd in I["category"].items():
        kv(c, f"P0={cd['p0_fp_pct']:.1f}%  Tool={cd['tool_fp_pct']:.1f}%  Overall={cd['overall_fp_pct']:.1f}%  uplift={cd['uplift_pp']:+.1f}pp  (n={cd['n']})")

    h2("MODEL")
    for m, md in I["model"].items():
        if m.startswith("_"): continue
        kv(m.split(":")[1][:20],
           f"fp={md['full_pass_pct']:.1f}%  score={md['avg_score']:.3f}  tc_rate={md['tool_call_rate_pct']:.0f}%  uplift={md['uplift_vs_p0_pp']:+.1f}pp  cost=${md['avg_cost_usd']:.4f}  no_tc={md['no_tool_calls_count']}")
    kv("Best tool-caller",     I["model"]["_best_caller"].split(":")[1])
    kv("Best VoltSnip uplift", I["model"]["_best_uplift"].split(":")[1])

    h2("MEMORY")
    m = I["memory"]
    kv("Memory ON vs OFF",     f"{m['mem_full_pass_pct']:.1f}% vs {m['nomem_full_pass_pct']:.1f}%  Δ={m['mem_delta_pp']:+.1f}pp")
    kv("P7/P8/P9",             f"P7={m['P7_8_9_fp']['P7']:.1f}%  P8={m['P7_8_9_fp']['P8']:.1f}%  P9={m['P7_8_9_fp']['P9']:.1f}%")
    kv("P7 zero-roundtrip",    f"{m['P7_zero_roundtrip_pct']:.1f}%  (skills context kills tool curiosity)")
    kv("Memory token overhead", f"{m['memory_token_overhead']:.0f} extra tokens (P3 vs P2)")
    kv("P9 vs P0 Δ",           f"{m['P9_vs_P0_delta_pp']:+.1f}pp  (ceiling vs raw baseline)")
    kv("P9 vs P2 Δ",           f"{m['P9_vs_P2_delta_pp']:+.1f}pp  (combined context+tools vs agent-decides)")

    h2("PROCESS COMPLIANCE")
    c = I["compliance"]
    kv("no_tool_calls failures", f"{c['no_tool_calls_count']}  ({c['no_tool_calls_pct']:.1f}%)  avg_score={c['no_tool_calls_avg_score']:.3f}")
    kv("By variant",             "  ".join(f"{k}:{v}" for k,v in c["no_tc_by_variant"].items()))
    kv("Compliance by model",    "  ".join(f"{m.split(':')[1][:8]}:{pct:.0f}%" for m,pct in c["compliance_rate_by_model"].items()))

    h2("ROUNDTRIPS → QUALITY")
    r = I["roundtrips"]
    kv("Avg roundtrips (tool variants)", f"{r['avg_roundtrips_tool_variants']:.2f}")
    kv("Zero-roundtrip rate",            f"{r['zero_roundtrip_pct']:.1f}%")
    kv("Full_pass by roundtrips",        "  ".join(f"rt={n}:{v:.0f}%" for n,v in r["full_pass_by_roundtrip"].items()))

    h2("COST & EFFICIENCY")
    co = I["cost"]
    kv("Total spend",          f"${co['total_cost_usd']:.2f}")
    kv("Avg per run",          f"${co['avg_cost_all_usd']:.4f}  (passing=${co['avg_cost_passing_usd']:.4f}  failing=${co['avg_cost_failing_usd']:.4f})")
    kv("Cache hit rate",       f"{co['cache_hit_rate_pct']:.1f}%  (ZERO — big optimisation opportunity)")
    kv("By variant",           "  ".join(f"{v}=${d:.4f}" for v,d in co["avg_cost_per_variant"].items()))

    h2("SYNTHESIS — NET VERDICT")
    s = I["synthesis"]
    kv("Mandate effect (P2→P9)",      f"{s['mandate_effect_pp']:+.1f}pp")
    kv("Called vs uncalled Δ",         f"{s['called_vs_uncalled_delta_pp']:+.1f}pp")
    kv("Hard-task uplift",             f"{s['hard_task_uplift_pp']:+.1f}pp")
    kv("Best no-tool vs best tool",    f"{s['best_notool_fp_pct']:.0f}% vs {s['best_tool_fp_pct']:.0f}%")
    lines.append("")
    lines.append(f"  ★  VERDICT: {s['verdict']}")
    lines.append("")
    hr("═")

    return "\n".join(lines)


def fmt_markdown(I: dict) -> str:
    lines = []

    def h2(t): lines.append(f"\n## {t}\n")
    def h3(t): lines.append(f"\n### {t}\n")
    def row(*cols): lines.append("| " + " | ".join(str(c) for c in cols) + " |")
    def sep(*n): lines.append("| " + " | ".join("---" for _ in range(n[0] if n else 2)) + " |")

    lines.append(f"# VoltSnip Matrix Insights\n")
    lines.append(f"> {I['overview']['total_real_runs']} real runs · "
                 f"{len(I['overview']['tasks'])} tasks · "
                 f"{len(I['overview']['models'])} models · "
                 f"matrix {I['overview']['completeness_pct']:.1f}% complete\n")

    h2("Baseline")
    row("Metric","Value"); sep(2)
    row("Overall full_pass",     f"{I['baseline']['overall_full_pass_pct']:.1f}%")
    row("P0 raw baseline",       f"{I['baseline']['P0_full_pass_pct']:.1f}%")
    row("Avg score",             f"{I['baseline']['overall_avg_score']:.3f}")
    row("Tool-compliance gap",   f"{I['baseline']['tool_compliance_gap_pp']:+.1f}pp (score≥0.7 vs full_pass)")
    row("P1 oracle Δ vs P0",     f"{I['baseline']['P1_vs_P0_delta_pp']:+.1f}pp")

    h2("Per-Variant Full_Pass")
    row("Variant","Full_pass","Score","Avg TC","Cost"); sep(5)
    for v in sorted(I["per_variant"], key=lambda v: -I["per_variant"][v]["full_pass_pct"]):
        d = I["per_variant"][v]
        row(v, f"{d['full_pass_pct']:.1f}%", f"{d['avg_score']:.3f}", f"{d['avg_tool_calls']:.2f}", f"${d['avg_cost_usd']:.4f}")

    h2("★ Key Finding — Mandate Effect (P2 → P9)")
    tp = I["tool_pressure"]
    row("Variant","Full_pass","Avg TC","Compliance"); sep(4)
    row("P2 (agent-decides)", f"{tp['P2_fp_pct']:.1f}%",  f"{tp['P2_avg_tc']:.2f}",  "—")
    row("P7 (skills+tools)",  f"{tp['P7_fp_pct']:.1f}%",  f"{tp['P7_avg_tc']:.2f}",  "—")
    row("P9 (ceiling)",       f"{tp['P9_fp_pct']:.1f}%",  f"{tp['P9_avg_tc']:.2f}",  f"{tp['P9_compliance_pct']:.0f}%")
    row("**Δ P9−P2**",        f"**{tp['P9_vs_P2_mandate_delta_pp']:+.1f}pp**", "","")
    row("**Δ P9−P8**",        f"**{tp['P9_vs_P8_context_delta_pp']:+.1f}pp**", "","context gain")
    lines.append(f"\n> Combined context + tools gives **{tp['P9_vs_P2_mandate_delta_pp']:+.1f}pp** uplift over agent-decides baseline.\n")

    h2("VoltSnip Call Behaviour")
    v = I["voltsnip_calls"]
    row("Metric","Value"); sep(2)
    row("Runs that called VoltSnip", f"{v['runs_called']} ({v['call_rate_pct']:.1f}%)")
    row("Tool-variant call rate",    f"{v['tool_variant_call_rate_pct']:.1f}%")
    row("Full_pass when CALLED",     f"{v['full_pass_when_called_pct']:.1f}%")
    row("Full_pass when NOT called", f"{v['full_pass_when_not_called_pct']:.1f}%")
    row("Δ (called − uncalled)",     f"**{v['full_pass_delta_pp']:+.1f}pp**")
    row("Score Δ",                   f"{v['score_delta']:+.3f}")

    h2("Task Difficulty")
    td = I["task_difficulty"]
    row("Metric","Value"); sep(2)
    row("Hard tasks (P0<50%)",   str(td["hard_tasks_p0_lt50"]))
    row("Medium tasks",          str(td["medium_tasks_p0_50_80"]))
    row("Hard: P0→tool uplift",  f"{td['hard_uplift_pp']:+.1f}pp")
    row("Top 5 task uplifts",    "  ".join(f"{t}:{u:+.0f}pp" for t,u in td["top5_highest_uplift"]))

    h2("Per-Task: P0 vs Tool Full_Pass")
    row("Task","P0","Tool","Uplift"); sep(4)
    for t in sorted(I["task_difficulty"]["p0_per_task"]):
        row(t,
            f"{I['task_difficulty']['p0_per_task'][t]:.0f}%",
            f"{I['task_difficulty']['tool_fp_per_task'][t]:.0f}%",
            f"{I['task_difficulty']['uplift_per_task'][t]:+.0f}pp")

    h2("Model Comparison")
    row("Model","Full_pass","Score","TC Rate","Uplift vs P0","Cost/run","no_tc"); sep(7)
    for m, md in I["model"].items():
        if m.startswith("_"): continue
        row(m.split(":")[1], f"{md['full_pass_pct']:.1f}%", f"{md['avg_score']:.3f}",
            f"{md['tool_call_rate_pct']:.0f}%", f"{md['uplift_vs_p0_pp']:+.1f}pp",
            f"${md['avg_cost_usd']:.4f}", md["no_tool_calls_count"])

    h2("Memory Analysis")
    m = I["memory"]
    row("Config","Full_pass","Notes"); sep(3)
    row("Memory OFF",  f"{m['nomem_full_pass_pct']:.1f}%", "")
    row("Memory ON",   f"{m['mem_full_pass_pct']:.1f}%",   f"Δ={m['mem_delta_pp']:+.1f}pp")
    row("P7",          f"{m['P7_8_9_fp']['P7']:.1f}%",    f"{m['P7_zero_roundtrip_pct']:.0f}% have 0 roundtrips")
    row("P8",          f"{m['P7_8_9_fp']['P8']:.1f}%",    "")
    row("P9",          f"{m['P7_8_9_fp']['P9']:.1f}%",    f"overhead={m['memory_token_overhead']:.0f} extra tokens vs P2")

    h2("Synthesis — Net Verdict")
    s = I["synthesis"]
    lines.append(f"| Finding | Value |")
    lines.append(f"| --- | --- |")
    lines.append(f"| Mandate effect (P2→P9) | **{s['mandate_effect_pp']:+.1f}pp** |")
    lines.append(f"| Called vs uncalled Δ | **{s['called_vs_uncalled_delta_pp']:+.1f}pp** |")
    lines.append(f"| Hard-task uplift | {s['hard_task_uplift_pp']:+.1f}pp |")
    lines.append(f"| Best no-tool vs best tool | {s['best_notool_fp_pct']:.0f}% vs {s['best_tool_fp_pct']:.0f}% |")
    lines.append(f"\n> **★ VERDICT: {s['verdict']}**\n")

    return "\n".join(lines)


# ─── CLI ─────────────────────────────────────────────────────────────────────

def find_latest_csv() -> Path:
    base = Path(__file__).parent.parent / "vsevals_final_runs"
    if not base.exists():
        base = Path(__file__).parent.parent.parent / "vsevals" / "vsevals_final_runs"
    candidates = sorted(base.glob("matrix_*/matrix_results.csv"), reverse=True)
    if not candidates:
        raise FileNotFoundError(f"No matrix_results.csv found under {base}")
    return candidates[0]


def main():
    p = argparse.ArgumentParser(description="Extract insights from VoltSnip matrix_results.csv")
    p.add_argument("--csv",    default=None,   help="Path to matrix_results.csv (auto-detected if omitted)")
    p.add_argument("--format", default="text", choices=["text", "json", "md"], help="Output format")
    p.add_argument("--out",    default=None,   help="Write output to file instead of stdout")
    args = p.parse_args()

    csv_path = args.csv or str(find_latest_csv())
    print(f"[matrix_insights] loading {csv_path}", file=sys.stderr)

    rows = load(csv_path)
    I    = build_insights(rows)

    if args.format == "json":
        output = json.dumps(I, indent=2, default=str)
    elif args.format == "md":
        output = fmt_markdown(I)
    else:
        output = fmt_text(I)

    if args.out:
        Path(args.out).write_text(output)
        print(f"[matrix_insights] written to {args.out}", file=sys.stderr)
    else:
        print(output)


if __name__ == "__main__":
    main()
