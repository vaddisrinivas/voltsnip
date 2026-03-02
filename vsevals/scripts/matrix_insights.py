#!/usr/bin/env python3
"""
matrix_insights.py — extract meaningful insights from a matrix_results.csv.

Usage:
    python vsevals/scripts/matrix_insights.py [--csv PATH] [--format {text,json,md}] [--out PATH]

Defaults to the latest matrix_results.csv found under common run directories.
"""

from __future__ import annotations

import argparse
import csv
import json
import statistics
import sys
from collections import defaultdict
from pathlib import Path


def flt(v, default: float = 0.0) -> float:
    try:
        if v in ("", None, "nan", "None"):
            return default
        return float(v)
    except (TypeError, ValueError):
        return default


def boo(v) -> bool:
    return str(v).strip().lower() in ("true", "1", "yes", "y")


def avg(lst, fn=None) -> float:
    vals = [fn(r) for r in lst] if fn else list(lst)
    vals = [v for v in vals if v == v and v is not None]
    return statistics.mean(vals) if vals else 0.0


def safe_std(lst) -> float:
    return statistics.stdev(lst) if len(lst) >= 2 else 0.0


def fp(lst) -> float:
    return (sum(1 for r in lst if r.get("_fp")) / len(lst) * 100) if lst else 0.0


def sc(lst) -> float:
    return avg(lst, lambda r: r.get("_score", 0.0))


def variant_sort_key(v: str) -> tuple[int, str]:
    if isinstance(v, str) and v.startswith("P") and v[1:].isdigit():
        return (int(v[1:]), v)
    return (10_000, str(v))


def load(path: str) -> list[dict]:
    with open(path, encoding="utf-8") as f:
        raw = list(csv.DictReader(f))

    rows = [
        r for r in raw
        if str(r.get("status", "")).lower() == "ok"
        and not str(r.get("model_name", "")).startswith("mock:")
    ]

    for r in rows:
        r["_fp"] = boo(r.get("full_pass", ""))
        r["_score"] = flt(r.get("overall_score", 0))
        r["_tc"] = int(flt(r.get("tool_call_count", 0)))
        r["_cost"] = flt(r.get("cost_usd", 0))
        r["_lat"] = flt(r.get("model_request_latency_ms", 0))
        r["_tok"] = int(flt(r.get("total_tokens", 0)))
        r["_pt"] = int(flt(r.get("prompt_tokens", 0)))
        r["_ct"] = int(flt(r.get("completion_tokens", 0)))
        r["_snip_inj"] = int(flt(r.get("snippet_injected_count", 0)))
        r["_snip_util"] = flt(r.get("snippet_utilized_fraction", 0))
        r["_rtrips"] = int(flt(r.get("tool_roundtrips_used", 0)))
        r["_hr"] = flt(r.get("hidden_requirements_score", 0))
        r["_si"] = flt(r.get("success_indicators_score", 0))
        r["_fm"] = flt(r.get("failure_modes_score", 0))
        r["_ec"] = flt(r.get("evaluation_criteria_score", 0))
        r["_pytest"] = boo(r.get("pytest_passed", ""))
        r["_py_ran"] = boo(r.get("pytest_ran", ""))
        r["_pfail"] = r.get("process_fail_reason", "")
        r["_ochar"] = int(flt(r.get("output_chars", 0)))
        r["_vs_tot"] = int(flt(r.get("voltsnip_constraints_total", 0)))
        r["_vs_rate"] = flt(r.get("voltsnip_constraint_pass_rate", 0))

        raw_tools = r.get("variant_tools_enabled")
        raw_memory = r.get("variant_memory_enabled")
        r["_v_tools"] = boo(raw_tools) if raw_tools not in (None, "") else None
        r["_v_memory"] = boo(raw_memory) if raw_memory not in (None, "") else None

    return rows


def _variant_flags(rows: list[dict], variants: list[str]) -> dict[str, dict[str, bool]]:
    out: dict[str, dict[str, bool]] = {}
    for v in variants:
        vr = [r for r in rows if r.get("variant_id") == v]
        tvals = [r["_v_tools"] for r in vr if r.get("_v_tools") is not None]
        mvals = [r["_v_memory"] for r in vr if r.get("_v_memory") is not None]

        tools_enabled = bool(sum(1 for x in tvals if x) >= (len(tvals) / 2.0)) if tvals else (v in {"P2", "P4", "P5", "P6"})
        memory_enabled = bool(sum(1 for x in mvals if x) >= (len(mvals) / 2.0)) if mvals else (v == "P3")

        out[v] = {
            "tools_enabled": tools_enabled,
            "memory_enabled": memory_enabled,
        }
    return out


def build_insights(rows: list[dict]) -> dict:
    if not rows:
        return {
            "overview": {
                "total_real_runs": 0,
                "tasks": [],
                "models": [],
                "variants": [],
                "tool_variants": [],
                "no_tool_variants": [],
                "memory_variants": [],
                "matrix_cells": 0,
                "expected_cells": 0,
                "completeness_pct": 0.0,
            }
        }

    models = sorted(set(r.get("model_name", "") for r in rows if r.get("model_name")))
    tasks = sorted(set(r.get("task_id", "") for r in rows if r.get("task_id")))
    cats = sorted(set(r.get("task_category", "") for r in rows if r.get("task_category")))
    variants = sorted(set(r.get("variant_id", "") for r in rows if r.get("variant_id")), key=variant_sort_key)

    vmap = {v: [r for r in rows if r.get("variant_id") == v] for v in variants}
    vflags = _variant_flags(rows, variants)
    tool_variants = [v for v in variants if vflags[v]["tools_enabled"]]
    notool_variants = [v for v in variants if not vflags[v]["tools_enabled"]]
    memory_variants = [v for v in variants if vflags[v]["memory_enabled"]]

    tv = [r for r in rows if r.get("variant_id") in set(tool_variants)]
    ntv = [r for r in rows if r.get("variant_id") in set(notool_variants)]
    called = [r for r in rows if r.get("_tc", 0) > 0]
    ncall = [r for r in rows if r.get("_tc", 0) == 0]
    has_s = [r for r in rows if r.get("_snip_inj", 0) > 0]
    no_s = [r for r in rows if r.get("_snip_inj", 0) == 0]
    pass_r = [r for r in rows if r.get("_fp")]
    fail_r = [r for r in rows if not r.get("_fp")]

    baseline_variant = "P0" if "P0" in variants else (notool_variants[0] if notool_variants else variants[0])
    primary_tool_variant = "P2" if "P2" in tool_variants else (tool_variants[0] if tool_variants else None)
    best_tool_variant = max(tool_variants, key=lambda v: fp(vmap[v])) if tool_variants else None
    best_notool_variant = max(notool_variants, key=lambda v: fp(vmap[v])) if notool_variants else None

    pfail = defaultdict(int)
    for r in rows:
        reason = r.get("_pfail", "")
        if reason:
            pfail[reason] += 1

    base_by_task = {
        t: fp([r for r in rows if r.get("task_id") == t and r.get("variant_id") == baseline_variant])
        for t in tasks
    }
    hard_tasks = [t for t, val in base_by_task.items() if val < 50]
    med_tasks = [t for t, val in base_by_task.items() if 50 <= val < 80]
    easy_tasks = [t for t, val in base_by_task.items() if val >= 80]

    hard_base = [r for r in rows if r.get("task_id") in hard_tasks and r.get("variant_id") == baseline_variant]
    hard_tool = [r for r in rows if r.get("task_id") in hard_tasks and r.get("variant_id") in set(tool_variants)]

    uplift_task = {
        t: fp([r for r in rows if r.get("task_id") == t and r.get("variant_id") in set(tool_variants)])
           - fp([r for r in rows if r.get("task_id") == t and r.get("variant_id") == baseline_variant])
        for t in tasks
    }
    top5_uplift = sorted(uplift_task.items(), key=lambda x: -x[1])[:5]
    top5_hurt = sorted(uplift_task.items(), key=lambda x: x[1])[:5]

    def model_tcr(model_name: str) -> float:
        mrows = [r for r in rows if r.get("model_name") == model_name and r.get("variant_id") in set(tool_variants)]
        return sum(1 for r in mrows if r.get("_tc", 0) > 0) / max(len(mrows), 1)

    model_uplift = {
        m: fp([r for r in rows if r.get("model_name") == m and r.get("variant_id") in set(tool_variants)])
           - fp([r for r in rows if r.get("model_name") == m and r.get("variant_id") == baseline_variant])
        for m in models
    }
    model_stdev = {
        m: safe_std([
            fp([r for r in rows if r.get("model_name") == m and r.get("task_id") == t])
            for t in tasks
            if any(r.get("model_name") == m and r.get("task_id") == t for r in rows)
        ])
        for m in models
    }

    rt_fps = {
        n: fp([r for r in tv if r.get("_rtrips", 0) == n])
        for n in range(0, 16)
        if any(r.get("_rtrips", 0) == n for r in tv)
    }

    primary_tool_rows = vmap.get(primary_tool_variant, []) if primary_tool_variant else []
    best_tool_rows = vmap.get(best_tool_variant, []) if best_tool_variant else []
    baseline_rows = vmap.get(baseline_variant, [])

    memory_rows = [r for r in rows if r.get("variant_id") in set(memory_variants)]
    non_memory_rows = [r for r in rows if r.get("variant_id") not in set(memory_variants)]

    I: dict = {}

    I["overview"] = {
        "total_real_runs": len(rows),
        "tasks": tasks,
        "models": models,
        "variants": variants,
        "tool_variants": tool_variants,
        "no_tool_variants": notool_variants,
        "memory_variants": memory_variants,
        "matrix_cells": len(rows),
        "expected_cells": len(tasks) * len(variants) * len(models),
        "completeness_pct": len(rows) / max(len(tasks) * len(variants) * len(models), 1) * 100,
    }

    I["baseline"] = {
        "baseline_variant": baseline_variant,
        "overall_full_pass_pct": round(fp(rows), 2),
        "overall_avg_score": round(sc(rows), 4),
        "baseline_full_pass_pct": round(fp(baseline_rows), 2),
        "baseline_avg_score": round(sc(baseline_rows), 4),
        "score_gte_0_70_pct": round(sum(1 for r in rows if r.get("_score", 0.0) >= 0.7) / len(rows) * 100, 2),
    }

    I["per_variant"] = {
        v: {
            "full_pass_pct": round(fp(vmap[v]), 2),
            "avg_score": round(sc(vmap[v]), 4),
            "n": len(vmap[v]),
            "avg_tool_calls": round(avg(vmap[v], lambda r: r.get("_tc", 0)), 2),
            "avg_cost_usd": round(avg(vmap[v], lambda r: r.get("_cost", 0.0)), 4),
            "avg_latency_ms": round(avg(vmap[v], lambda r: r.get("_lat", 0.0)), 0),
            "tools_enabled": vflags[v]["tools_enabled"],
            "memory_enabled": vflags[v]["memory_enabled"],
        }
        for v in variants
    }

    I["tool_vs_notool"] = {
        "tool_full_pass_pct": round(fp(tv), 2),
        "notool_full_pass_pct": round(fp(ntv), 2),
        "delta_pp": round(fp(tv) - fp(ntv), 2),
        "tool_avg_score": round(sc(tv), 4),
        "notool_avg_score": round(sc(ntv), 4),
        "score_delta": round(sc(tv) - sc(ntv), 4),
        "best_variant": max(variants, key=lambda v: fp(vmap[v])) if variants else None,
        "worst_variant": min(variants, key=lambda v: fp(vmap[v])) if variants else None,
    }

    I["voltsnip_calls"] = {
        "runs_called": len(called),
        "runs_not_called": len(ncall),
        "call_rate_pct": round(len(called) / len(rows) * 100, 2),
        "tool_variant_call_rate_pct": round(sum(1 for r in tv if r.get("_tc", 0) > 0) / max(len(tv), 1) * 100, 2),
        "full_pass_when_called_pct": round(fp(called), 2),
        "full_pass_when_not_called_pct": round(fp(ncall), 2),
        "full_pass_delta_pp": round(fp(called) - fp(ncall), 2),
        "score_when_called": round(sc(called), 4),
        "score_when_not_called": round(sc(ncall), 4),
        "score_delta": round(sc(called) - sc(ncall), 4),
        "call_rate_per_variant": {
            v: round(sum(1 for r in vmap[v] if r.get("_tc", 0) > 0) / max(len(vmap[v]), 1) * 100, 1)
            for v in tool_variants
        },
        "avg_calls_per_tool_run": round(avg(tv, lambda r: r.get("_tc", 0)), 2),
        "max_calls_single_run": max((r.get("_tc", 0) for r in rows), default=0),
    }

    I["task_difficulty"] = {
        "baseline_variant": baseline_variant,
        "hard_tasks_base_lt50": hard_tasks,
        "medium_tasks_base_50_80": med_tasks,
        "easy_tasks_base_gte80": easy_tasks,
        "baseline_per_task": {t: round(base_by_task[t], 1) for t in tasks},
        "tool_fp_per_task": {
            t: round(fp([r for r in rows if r.get("task_id") == t and r.get("variant_id") in set(tool_variants)]), 1)
            for t in tasks
        },
        "uplift_per_task": {t: round(uplift_task[t], 1) for t in tasks},
        "top5_highest_uplift": top5_uplift,
        "top5_biggest_hurt": top5_hurt,
        "hard_base_fp_pct": round(fp(hard_base), 2),
        "hard_tool_fp_pct": round(fp(hard_tool), 2),
        "hard_uplift_pp": round(fp(hard_tool) - fp(hard_base), 2),
    }

    I["category"] = {
        c: {
            "n": len([r for r in rows if r.get("task_category") == c]),
            "overall_fp_pct": round(fp([r for r in rows if r.get("task_category") == c]), 2),
            "base_fp_pct": round(fp([r for r in rows if r.get("task_category") == c and r.get("variant_id") == baseline_variant]), 2),
            "tool_fp_pct": round(fp([r for r in rows if r.get("task_category") == c and r.get("variant_id") in set(tool_variants)]), 2),
        }
        for c in cats
    }

    I["model"] = {
        m: {
            "full_pass_pct": round(fp([r for r in rows if r.get("model_name") == m]), 2),
            "avg_score": round(sc([r for r in rows if r.get("model_name") == m]), 4),
            "tool_call_rate_pct": round(model_tcr(m) * 100, 1),
            "tool_fp_pct": round(fp([r for r in rows if r.get("model_name") == m and r.get("variant_id") in set(tool_variants)]), 2),
            "base_fp_pct": round(fp([r for r in rows if r.get("model_name") == m and r.get("variant_id") == baseline_variant]), 2),
            "uplift_vs_base_pp": round(model_uplift[m], 2),
            "no_tool_calls_count": sum(1 for r in rows if r.get("model_name") == m and r.get("_pfail") == "no_tool_calls"),
            "avg_cost_usd": round(avg([r for r in rows if r.get("model_name") == m], lambda r: r.get("_cost", 0.0)), 4),
            "avg_latency_ms": round(avg([r for r in rows if r.get("model_name") == m], lambda r: r.get("_lat", 0.0)), 0),
            "task_fp_stdev": round(model_stdev[m], 2),
        }
        for m in models
    }

    I["memory"] = {
        "memory_variants": memory_variants,
        "mem_full_pass_pct": round(fp(memory_rows), 2),
        "nomem_full_pass_pct": round(fp(non_memory_rows), 2),
        "mem_delta_pp": round(fp(memory_rows) - fp(non_memory_rows), 2),
        "memory_fp_by_variant": {v: round(fp(vmap[v]), 2) for v in memory_variants},
    }

    I["snippets"] = {
        "injected_full_pass_pct": round(fp(has_s), 2),
        "no_snip_full_pass_pct": round(fp(no_s), 2),
        "delta_pp": round(fp(has_s) - fp(no_s), 2),
        "injected_avg_score": round(sc(has_s), 4),
        "no_snip_avg_score": round(sc(no_s), 4),
        "avg_utilized_fraction": round(avg([r for r in tv if r.get("_snip_inj", 0) > 0], lambda r: r.get("_snip_util", 0.0)), 3),
    }

    I["tool_pressure"] = {
        "baseline_variant": baseline_variant,
        "primary_tool_variant": primary_tool_variant,
        "best_tool_variant": best_tool_variant,
        "baseline_fp_pct": round(fp(baseline_rows), 2),
        "primary_tool_fp_pct": round(fp(primary_tool_rows), 2),
        "best_tool_fp_pct": round(fp(best_tool_rows), 2),
        "primary_tool_avg_tc": round(avg(primary_tool_rows, lambda r: r.get("_tc", 0)), 2),
        "best_tool_avg_tc": round(avg(best_tool_rows, lambda r: r.get("_tc", 0)), 2),
        "primary_tool_compliance_pct": round(sum(1 for r in primary_tool_rows if r.get("_tc", 0) > 0) / max(len(primary_tool_rows), 1) * 100, 1),
        "primary_tool_vs_base_delta_pp": round(fp(primary_tool_rows) - fp(baseline_rows), 2),
        "best_tool_vs_base_delta_pp": round(fp(best_tool_rows) - fp(baseline_rows), 2),
    }

    I["compliance"] = {
        "no_tool_calls_count": pfail.get("no_tool_calls", 0),
        "no_tool_calls_pct": round(pfail.get("no_tool_calls", 0) / len(rows) * 100, 2),
        "all_fail_reasons": dict(sorted(pfail.items(), key=lambda x: -x[1])),
        "no_tc_by_variant": {
            v: sum(1 for r in rows if r.get("variant_id") == v and r.get("_pfail") == "no_tool_calls")
            for v in tool_variants
        },
    }

    I["roundtrips"] = {
        "avg_roundtrips_tool_variants": round(avg(tv, lambda r: r.get("_rtrips", 0)), 2),
        "zero_roundtrip_pct": round(sum(1 for r in tv if r.get("_rtrips", 0) == 0) / max(len(tv), 1) * 100, 1),
        "full_pass_by_roundtrip": {n: round(rt_fps[n], 1) for n in sorted(rt_fps)},
    }

    I["cost"] = {
        "avg_cost_all_usd": round(avg(rows, lambda r: r.get("_cost", 0.0)), 4),
        "total_cost_usd": round(sum(r.get("_cost", 0.0) for r in rows), 2),
        "avg_cost_passing_usd": round(avg(pass_r, lambda r: r.get("_cost", 0.0)), 4),
        "avg_cost_failing_usd": round(avg(fail_r, lambda r: r.get("_cost", 0.0)), 4),
        "avg_cost_per_variant": {v: round(avg(vmap[v], lambda r: r.get("_cost", 0.0)), 4) for v in variants},
    }

    I["pytest"] = {
        "ran_pct": round(sum(1 for r in rows if r.get("_py_ran")) / len(rows) * 100, 1),
        "pass_pct": round(sum(1 for r in rows if r.get("_py_ran") and r.get("_pytest")) / max(sum(1 for r in rows if r.get("_py_ran")), 1) * 100, 1),
    }

    if I["tool_pressure"]["best_tool_vs_base_delta_pp"] > 20:
        verdict = "STRONG: tool-enabled setup materially improves pass rate."
    elif I["tool_vs_notool"]["delta_pp"] > 8:
        verdict = "MODERATE: tool-enabled variants help, but uplift is mixed."
    elif I["voltsnip_calls"]["full_pass_delta_pp"] > 8:
        verdict = "MIXED: runs that call tools perform better, but setup consistency limits gains."
    else:
        verdict = "WEAK: little measured uplift; investigate task difficulty, prompts, and tool behavior."

    I["synthesis"] = {
        "baseline_variant": baseline_variant,
        "primary_tool_variant": primary_tool_variant,
        "best_tool_variant": best_tool_variant,
        "best_notool_variant": best_notool_variant,
        "primary_tool_vs_base_delta_pp": I["tool_pressure"]["primary_tool_vs_base_delta_pp"],
        "best_tool_vs_base_delta_pp": I["tool_pressure"]["best_tool_vs_base_delta_pp"],
        "called_vs_uncalled_delta_pp": I["voltsnip_calls"]["full_pass_delta_pp"],
        "hard_task_uplift_pp": I["task_difficulty"]["hard_uplift_pp"],
        "verdict": verdict,
    }

    return I


def fmt_text(I: dict) -> str:
    if I.get("overview", {}).get("total_real_runs", 0) == 0:
        return "No eligible rows found in matrix_results.csv (need status=ok and non-mock models)."

    lines: list[str] = []
    W = 108

    def hr(char="-"):
        lines.append(char * W)

    def h2(t: str):
        hr("=")
        lines.append(f"{t}")
        hr("=")

    def kv(k: str, v: str):
        lines.append(f"{k:<44} {v}")

    h2("Matrix Overview")
    ov = I["overview"]
    kv("Rows", str(ov["total_real_runs"]))
    kv("Tasks", str(len(ov["tasks"])))
    kv("Models", str(len(ov["models"])))
    kv("Variants", ", ".join(ov["variants"]))
    kv("Tool variants", ", ".join(ov["tool_variants"]) or "(none)")
    kv("No-tool variants", ", ".join(ov["no_tool_variants"]) or "(none)")
    kv("Completeness", f"{ov['completeness_pct']:.1f}%")

    h2("Baseline")
    base = I["baseline"]
    kv("Baseline variant", base["baseline_variant"])
    kv("Overall full_pass", f"{base['overall_full_pass_pct']:.1f}%")
    kv("Baseline full_pass", f"{base['baseline_full_pass_pct']:.1f}%")
    kv("Overall avg score", f"{base['overall_avg_score']:.3f}")

    h2("Per Variant")
    for v in sorted(I["per_variant"], key=lambda x: -I["per_variant"][x]["full_pass_pct"]):
        d = I["per_variant"][v]
        flags = []
        if d["tools_enabled"]:
            flags.append("tools")
        if d["memory_enabled"]:
            flags.append("memory")
        flag_txt = f" [{','.join(flags)}]" if flags else ""
        kv(v + flag_txt, f"fp={d['full_pass_pct']:.1f}% score={d['avg_score']:.3f} avg_tc={d['avg_tool_calls']:.2f}")

    h2("Tool Signal")
    tvn = I["tool_vs_notool"]
    kv("Tool full_pass", f"{tvn['tool_full_pass_pct']:.1f}%")
    kv("No-tool full_pass", f"{tvn['notool_full_pass_pct']:.1f}%")
    kv("Delta", f"{tvn['delta_pp']:+.1f}pp")

    vp = I["voltsnip_calls"]
    kv("Call rate", f"{vp['call_rate_pct']:.1f}%")
    kv("Called vs uncalled", f"{vp['full_pass_when_called_pct']:.1f}% vs {vp['full_pass_when_not_called_pct']:.1f}% ({vp['full_pass_delta_pp']:+.1f}pp)")

    h2("Synthesis")
    s = I["synthesis"]
    kv("Baseline variant", s["baseline_variant"])
    kv("Primary tool variant", str(s["primary_tool_variant"]))
    kv("Best tool variant", str(s["best_tool_variant"]))
    kv("Primary tool uplift", f"{s['primary_tool_vs_base_delta_pp']:+.1f}pp")
    kv("Best tool uplift", f"{s['best_tool_vs_base_delta_pp']:+.1f}pp")
    kv("Hard-task uplift", f"{s['hard_task_uplift_pp']:+.1f}pp")
    kv("Verdict", s["verdict"])

    return "\n".join(lines)


def fmt_markdown(I: dict) -> str:
    if I.get("overview", {}).get("total_real_runs", 0) == 0:
        return "No eligible rows found in matrix_results.csv (need status=ok and non-mock models)."

    ov = I["overview"]
    lines = [
        "# Matrix Insights",
        f"> {ov['total_real_runs']} real runs · {len(ov['tasks'])} tasks · {len(ov['models'])} models · {ov['completeness_pct']:.1f}% complete",
        "",
        "## Baseline",
        "| Metric | Value |",
        "| --- | --- |",
        f"| Baseline variant | {I['baseline']['baseline_variant']} |",
        f"| Overall full_pass | {I['baseline']['overall_full_pass_pct']:.1f}% |",
        f"| Baseline full_pass | {I['baseline']['baseline_full_pass_pct']:.1f}% |",
        f"| Overall avg score | {I['baseline']['overall_avg_score']:.3f} |",
        "",
        "## Per Variant",
        "| Variant | Full_pass | Score | Avg tool calls | Flags |",
        "| --- | --- | --- | --- | --- |",
    ]

    for v in sorted(I["per_variant"], key=lambda x: -I["per_variant"][x]["full_pass_pct"]):
        d = I["per_variant"][v]
        flags = []
        if d["tools_enabled"]:
            flags.append("tools")
        if d["memory_enabled"]:
            flags.append("memory")
        lines.append(f"| {v} | {d['full_pass_pct']:.1f}% | {d['avg_score']:.3f} | {d['avg_tool_calls']:.2f} | {', '.join(flags) or '-'} |")

    s = I["synthesis"]
    lines += [
        "",
        "## Key Findings",
        "| Finding | Value |",
        "| --- | --- |",
        f"| Primary tool uplift vs baseline | {s['primary_tool_vs_base_delta_pp']:+.1f}pp |",
        f"| Best tool uplift vs baseline | {s['best_tool_vs_base_delta_pp']:+.1f}pp |",
        f"| Called vs uncalled delta | {s['called_vs_uncalled_delta_pp']:+.1f}pp |",
        f"| Hard-task uplift | {s['hard_task_uplift_pp']:+.1f}pp |",
        f"| Verdict | **{s['verdict']}** |",
    ]

    return "\n".join(lines)


def find_latest_csv() -> Path:
    root = Path(__file__).resolve().parent.parent
    bases = [
        root / "vsevals_runs_clean",
        root / "vsevals_runs",
        root / "vsevals_final_runs",
        root.parent / "vsevals_runs_clean",
        root.parent / "vsevals_runs",
        root.parent / "vsevals_final_runs",
    ]

    candidates: list[Path] = []
    for base in bases:
        if base.exists():
            candidates.extend(base.glob("matrix_*/matrix_results.csv"))
    if not candidates:
        raise FileNotFoundError("No matrix_results.csv found in known run directories")

    return sorted(candidates, key=lambda p: p.stat().st_mtime, reverse=True)[0]


def main() -> None:
    parser = argparse.ArgumentParser(description="Extract insights from matrix_results.csv")
    parser.add_argument("--csv", default=None, help="Path to matrix_results.csv (auto-detect if omitted)")
    parser.add_argument("--format", default="text", choices=["text", "json", "md"], help="Output format")
    parser.add_argument("--out", default=None, help="Write output to file instead of stdout")
    args = parser.parse_args()

    csv_path = Path(args.csv) if args.csv else find_latest_csv()
    print(f"[matrix_insights] loading {csv_path}", file=sys.stderr)

    rows = load(str(csv_path))
    insights = build_insights(rows)

    if args.format == "json":
        output = json.dumps(insights, indent=2, default=str)
    elif args.format == "md":
        output = fmt_markdown(insights)
    else:
        output = fmt_text(insights)

    if args.out:
        Path(args.out).write_text(output, encoding="utf-8")
        print(f"[matrix_insights] written to {args.out}", file=sys.stderr)
    else:
        print(output)


if __name__ == "__main__":
    main()
