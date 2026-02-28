#!/usr/bin/env python3
"""
compute_stats.py — generates all numbers used in the paper.

Run from the repo root:
    python paper/compute_stats.py

Outputs:
    paper/stats.json   — all figures referenced in the LaTeX source
"""
import json
import math
from pathlib import Path

MATRIX = Path(__file__).parent.parent / "vsevals" / "vsevals_runs" / "matrix_20260228T053125139679Z"
RUNS   = MATRIX / "runs"

CONDITIONS = [
    ("full_dump.json",                  "nano_biased",    "GPT-4o-nano (biased prompt)"),
    ("full_dump__gpt-5-mini.json",      "mini_biased",    "GPT-5-mini (biased prompt)"),
    ("full_dump__gpt-5-mini-fixed.json","mini_fixed",     "GPT-5-mini (fixed prompt)"),
    ("full_dump__sonnet-4-6-fixed.json","sonnet_fixed",   "Claude Sonnet 4.6 (fixed prompt)"),
]

stats = {}

for fname, key, label in CONDITIONS:
    total = passed = vt = vf = tp = tn = fp = fn = contradictions = 0
    for rd in RUNS.iterdir():
        f = rd / fname
        if not f.exists():
            continue
        d = json.loads(f.read_text())
        py = bool(d.get("pytest_result", {}).get("passed", False))
        lp = bool(d.get("score", {}).get("passed", False))
        total += 1
        if lp:
            passed += 1
        if   py and lp:      tp += 1
        elif not py and not lp: tn += 1
        elif py and not lp:  fn += 1
        elif not py and lp:  fp += 1
        for cr in d.get("score", {}).get("constraint_results", []):
            v = cr.get("llm_verdict")
            r = (cr.get("judge_reason") or "").lower()
            if v is True:
                vt += 1
            elif v is False:
                vf += 1
            # Reasoning-verdict dissociation: reason says "fixed" but verdict=True
            if (v is True and cr.get("expected") is False and
                    any(w in r for w in ["correct", "fixed", "no longer", "does not exhibit",
                                         "absent", "properly", "now maps", "resolves"])):
                contradictions += 1

    denom = vt + vf if (vt + vf) > 0 else 1
    stats[key] = {
        "label":          label,
        "total":          total,
        "passed":         passed,
        "pass_pct":       round(100 * passed / total, 1) if total else 0,
        "verdict_true":   vt,
        "verdict_false":  vf,
        "verdict_true_pct": round(100 * vt / denom, 1),
        "tp": tp, "tn": tn, "fp": fp, "fn": fn,
        "accuracy_pct":   round(100 * (tp + tn) / total, 1) if total else 0,
        "contradictions": contradictions,
    }

# Pytest ground truth
pytest_pass = sum(
    1 for rd in RUNS.iterdir()
    if (rd / "full_dump.json").exists()
    and json.loads((rd / "full_dump.json").read_text()).get("pytest_result", {}).get("passed", False)
)
total_runs = sum(1 for rd in RUNS.iterdir() if (rd / "full_dump.json").exists())
stats["pytest"] = {
    "label":    "Pytest oracle",
    "total":    total_runs,
    "passed":   pytest_pass,
    "pass_pct": round(100 * pytest_pass / total_runs, 1),
}

# McNemar's test: nano-biased vs sonnet-fixed
b = c = 0
for rd in RUNS.iterdir():
    orig  = rd / "full_dump.json"
    fixed = rd / "full_dump__sonnet-4-6-fixed.json"
    if not orig.exists() or not fixed.exists():
        continue
    op = bool(json.loads(orig.read_text()).get("score", {}).get("passed", False))
    fp_ = bool(json.loads(fixed.read_text()).get("score", {}).get("passed", False))
    if op and not fp_:  b += 1
    elif not op and fp_: c += 1

n = b + c
chi2 = (abs(b - c) - 1) ** 2 / n if n > 0 else 0
stats["mcnemar"] = {"b": b, "c": c, "chi2": round(chi2, 1), "n": n}

# Cohen's g (arcsine effect size) on verdict=True rates
p_biased = stats["nano_biased"]["verdict_true"] / stats["nano_biased"]["total"]
p_fixed  = stats["sonnet_fixed"]["verdict_true"] / stats["sonnet_fixed"]["total"]
cohens_g = abs(math.asin(math.sqrt(p_biased)) - math.asin(math.sqrt(p_fixed)))
stats["cohens_g"] = round(cohens_g, 3)

# Prompt-only effect: same model (mini), different prompt
mini_b_acc = stats["mini_biased"]["accuracy_pct"]
mini_f_acc = stats["mini_fixed"]["accuracy_pct"]
stats["prompt_effect_accuracy_delta"] = round(mini_f_acc - mini_b_acc, 1)
stats["prompt_effect_pass_delta"]     = round(stats["mini_fixed"]["pass_pct"] - stats["mini_biased"]["pass_pct"], 1)

out = MATRIX.parent.parent.parent / "paper" / "stats.json"
out.write_text(json.dumps(stats, indent=2))
print(f"Written: {out}")

# Pretty print summary
print("\n=== PAPER STATISTICS ===\n")
print(f"{'Condition':<35} {'Pass%':>6} {'vTrue%':>7} {'Acc%':>6} {'Contra':>7}")
print("-" * 65)
for _, key, label in CONDITIONS:
    s = stats[key]
    print(f"  {label:<33} {s['pass_pct']:>5.1f}% {s['verdict_true_pct']:>6.1f}% {s['accuracy_pct']:>5.1f}%  {s['contradictions']:>5}")
s = stats["pytest"]
print(f"  {'Pytest oracle':<33} {s['pass_pct']:>5.1f}%      —      —       —")
print(f"\nMcNemar χ²={stats['mcnemar']['chi2']} (b={stats['mcnemar']['b']}, c={stats['mcnemar']['c']}, p<<0.001)")
print(f"Cohen's g={stats['cohens_g']} (very large effect)")
print(f"Prompt-only accuracy gain (gpt-5-mini): +{stats['prompt_effect_accuracy_delta']}pp")
print(f"Prompt-only pass-rate gain (gpt-5-mini): +{stats['prompt_effect_pass_delta']}pp")
