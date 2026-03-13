#!/usr/bin/env python3
"""
analyze_tool_calls.py
=====================
Parse batch_1 CSV run artefacts and produce a per-variant tool-call summary.

Outputs:
  - Console table: mean tool_call_count and tool_roundtrips_used per variant,
    broken down by pass/fail
  - vsevals/analysis/tool_calls_summary.csv

Usage:
    uv run python3 scripts/analyze_tool_calls.py
    uv run python3 scripts/analyze_tool_calls.py --model haiku
    uv run python3 scripts/analyze_tool_calls.py --model codex
"""

import argparse
import csv
import io
import sys
from pathlib import Path
from collections import defaultdict

BATCH1_DIR = Path(__file__).parent.parent / "vsevals_runs" / "batch_1"
RUNS_DIR = Path(__file__).parent.parent / "vsevals_runs"
OUTPUT_DIR = Path(__file__).parent.parent / "analysis"

HAIKU_DIRS = [
    "matrix_20260303T193221340869Z",  # Haiku Run 1
    "matrix_20260303T201709883387Z",  # Haiku Run 2
    "matrix_20260303T215606747051Z",  # Haiku Run 3
]
CODEX_DIRS = [
    "matrix_20260303T193214057044Z",  # Codex Run 1
    "matrix_20260303T201241727101Z",  # Codex Run 2
    "matrix_20260304T083357237819Z",  # Codex Run 3
]

TOOL_VARIANTS = {"P3", "P4", "P5", "P6", "P7", "P8"}
ALL_VARIANTS = ["P0", "P1", "P2", "P3", "P4", "P5", "P6", "P7", "P8"]
SIGNAL_BUGS = {
    "BUG42", "BUG43", "BUG44", "BUG45", "BUG46", "BUG47",
    "BUG49", "BUG50", "BUG51", "BUG52", "BUG53", "BUG54", "BUG55", "BUG56", "BUG57",
    "BUG60", "BUG61",
    "BUG63", "BUG64", "BUG65", "BUG66", "BUG67",
    "BUG69", "BUG70",
}


def load_csvs(run_dirs: list[str]) -> list[dict]:
    rows = []
    for d in run_dirs:
        # Check batch_1 first, then fall back to vsevals_runs root
        csv_path = BATCH1_DIR / d / "matrix_results.csv"
        if not csv_path.exists():
            csv_path = RUNS_DIR / d / "matrix_results.csv"
        if not csv_path.exists():
            print(f"  [warn] missing: {csv_path}", file=sys.stderr)
            continue
        with open(csv_path, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                if row.get("status") == "ok":
                    row["_run_dir"] = d
                    rows.append(row)
    return rows


def safe_int(val, default=0):
    try:
        return int(float(val)) if val not in ("", None) else default
    except (ValueError, TypeError):
        return default


def safe_float(val, default=0.0):
    try:
        return float(val) if val not in ("", None) else default
    except (ValueError, TypeError):
        return default


def analyze(rows: list[dict], signal_only: bool = True, label: str = ""):
    if signal_only:
        rows = [r for r in rows if r["task_id"].upper() in SIGNAL_BUGS]

    # Group: variant -> pass/fail -> list of (tool_call_count, roundtrips)
    data: dict[str, dict[str, list]] = defaultdict(lambda: {"pass": [], "fail": []})

    for row in rows:
        variant = row.get("variant_id", "").upper()
        passed = row.get("pytest_passed", "False") == "True"
        tc = safe_int(row.get("tool_call_count", 0))
        rtrips = safe_int(row.get("tool_roundtrips_used", 0))
        budget = safe_float(row.get("tool_budget_utilization", 0.0))
        key = "pass" if passed else "fail"
        data[variant][key].append({
            "tool_call_count": tc,
            "roundtrips": rtrips,
            "budget_util": budget,
        })

    # Print table
    header = f"\n{'='*70}\n  Tool-call analysis — {label}"
    if signal_only:
        header += " (signal bugs only)"
    print(header)
    print(f"{'='*70}")
    print(f"{'Variant':<8} {'State':<6} {'N':>5}  {'Mean calls':>10}  {'Mean trips':>10}  {'Budget%':>8}")
    print(f"{'-'*70}")

    summary_rows = []
    for variant in ALL_VARIANTS:
        if variant not in data:
            continue
        for state in ("pass", "fail"):
            entries = data[variant][state]
            n = len(entries)
            if n == 0:
                continue
            mean_tc = sum(e["tool_call_count"] for e in entries) / n
            mean_rt = sum(e["roundtrips"] for e in entries) / n
            mean_bu = sum(e["budget_util"] for e in entries) / n
            marker = "✓" if state == "pass" else "✗"
            print(f"{variant:<8} {marker:<6} {n:>5}  {mean_tc:>10.1f}  {mean_rt:>10.1f}  {mean_bu*100:>7.1f}%")
            summary_rows.append({
                "model_group": label,
                "variant": variant,
                "state": state,
                "n": n,
                "mean_tool_call_count": round(mean_tc, 2),
                "mean_roundtrips": round(mean_rt, 2),
                "mean_budget_utilization": round(mean_bu, 4),
            })
    print(f"{'='*70}\n")
    return summary_rows


def main():
    parser = argparse.ArgumentParser(description="Analyze tool call counts from batch_1 runs.")
    parser.add_argument("--model", choices=["haiku", "codex", "all"], default="all",
                        help="Which model group to analyze (default: all)")
    parser.add_argument("--all-bugs", action="store_true",
                        help="Include noisy bugs (default: signal bugs only)")
    args = parser.parse_args()

    signal_only = not args.all_bugs
    all_summary = []

    if args.model in ("haiku", "all"):
        print("Loading Haiku runs...", file=sys.stderr)
        haiku_rows = load_csvs(HAIKU_DIRS)
        print(f"  Loaded {len(haiku_rows)} ok rows from {len(HAIKU_DIRS)} runs.", file=sys.stderr)
        all_summary += analyze(haiku_rows, signal_only=signal_only, label="Haiku (claude-haiku-4-5)")

    if args.model in ("codex", "all"):
        print("Loading Codex runs...", file=sys.stderr)
        codex_rows = load_csvs(CODEX_DIRS)
        print(f"  Loaded {len(codex_rows)} ok rows from {len(CODEX_DIRS)} runs.", file=sys.stderr)
        all_summary += analyze(codex_rows, signal_only=False, label="Codex (gpt-5.1-codex-mini, all bugs)")

    # Write CSV
    OUTPUT_DIR.mkdir(exist_ok=True)
    out_path = OUTPUT_DIR / "tool_calls_summary.csv"
    if all_summary:
        fieldnames = list(all_summary[0].keys())
        with open(out_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(all_summary)
        print(f"Wrote {out_path}")


if __name__ == "__main__":
    main()
