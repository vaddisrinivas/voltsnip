#!/usr/bin/env python3
"""
analyze_retrieval_quality.py
============================
Parse batch_1 CSV run artefacts and compute per-variant retrieval quality
metrics: recall@k, precision, and correlation with pytest pass.

The CSV already contains:
  - required_snippet_keys         : gold required snippet keys (;-separated)
  - required_snippet_hit_keys     : required snippets that were retrieved
  - required_snippet_missing_keys : required snippets NOT retrieved
  - required_snippet_coverage     : fraction of required snippets retrieved (recall)
  - snippet_count                 : total snippets retrieved / injected
  - snippet_injected_count        : snippets injected (P3 oracle)
  - snippet_utilized_count        : snippets the model "utilized"

Outputs:
  - Console tables: per-variant recall, precision, full-coverage rate, pass rate
  - vsevals/analysis/retrieval_quality.csv

Usage:
    uv run python3 scripts/analyze_retrieval_quality.py
    uv run python3 scripts/analyze_retrieval_quality.py --model haiku
"""

import argparse
import csv
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

# Variants that do retrieval (P3=oracle injected, P2/P4/P5/P6=autonomous)
RETRIEVAL_VARIANTS = {"P2", "P3", "P4", "P5", "P6"}
ALL_VARIANTS = ["P0", "P1", "P2", "P3", "P4", "P5", "P6"]

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


def parse_keys(s: str) -> list[str]:
    """Parse ;-separated snippet key string into a list, ignoring blanks."""
    if not s:
        return []
    return [k.strip() for k in s.split(";") if k.strip()]


def compute_precision(retrieved_keys: list[str], required_keys: list[str]) -> float:
    """Fraction of retrieved snippets that are required (useful)."""
    if not retrieved_keys:
        return 0.0
    required_set = set(required_keys)
    return sum(1 for k in retrieved_keys if k in required_set) / len(retrieved_keys)


def analyze(rows: list[dict], signal_only: bool = True, label: str = ""):
    if signal_only:
        rows = [r for r in rows if r["task_id"].upper() in SIGNAL_BUGS]

    # Per-variant stats
    stats: dict[str, dict] = defaultdict(lambda: {
        "n": 0,
        "n_pass": 0,
        "recall_sum": 0.0,
        "precision_sum": 0.0,
        "full_coverage": 0,          # runs where all required snippets were retrieved
        "pass_with_full_coverage": 0,
        "pass_without_full_coverage": 0,
        "retrieved_counts": [],
    })

    for row in rows:
        variant = row.get("variant_id", "").upper()
        passed = row.get("pytest_passed", "False") == "True"

        required_keys = parse_keys(row.get("required_snippet_keys", ""))
        hit_keys = parse_keys(row.get("required_snippet_hit_keys", ""))
        # For P3 oracle, snippets are injected not "retrieved" in the usual sense
        # but required_snippet_coverage still reflects coverage
        coverage = safe_float(row.get("required_snippet_coverage", 0.0))

        # All snippets available to the model (retrieved or injected)
        snippet_count = safe_int(row.get("snippet_count", 0)) + safe_int(row.get("snippet_injected_count", 0))

        # For precision: among snippets the model had access to, how many were required?
        all_retrieved = parse_keys(row.get("retrieved_snippet_keys", ""))
        # If P3, also add injected keys (already in required_snippet_hit_keys)
        precision = compute_precision(all_retrieved, required_keys) if all_retrieved else (
            1.0 if hit_keys else 0.0  # oracle: injected exactly what's needed
        )

        full_cov = len(required_keys) > 0 and coverage >= 1.0

        s = stats[variant]
        s["n"] += 1
        s["n_pass"] += int(passed)
        s["recall_sum"] += coverage
        s["precision_sum"] += precision
        s["full_coverage"] += int(full_cov)
        s["retrieved_counts"].append(snippet_count)
        if full_cov:
            s["pass_with_full_coverage"] += int(passed)
        else:
            s["pass_without_full_coverage"] += int(passed)

    # Print table
    header = f"\n{'='*80}\n  Retrieval quality — {label}"
    if signal_only:
        header += " (signal bugs only)"
    print(header)
    print(f"{'='*80}")
    print(f"{'Variant':<8} {'N':>5}  {'Pass%':>6}  {'Recall':>7}  {'Precis':>7}  "
          f"{'FullCov%':>9}  {'Pass|FullCov':>13}  {'Pass|Partial':>13}")
    print(f"{'-'*80}")

    summary_rows = []
    for variant in ALL_VARIANTS:
        if variant not in stats or stats[variant]["n"] == 0:
            continue
        s = stats[variant]
        n = s["n"]
        pass_rate = s["n_pass"] / n
        recall = s["recall_sum"] / n
        precision = s["precision_sum"] / n
        full_cov_rate = s["full_coverage"] / n
        n_full = s["full_coverage"]
        n_partial = n - n_full
        pass_fc = s["pass_with_full_coverage"] / n_full if n_full > 0 else float("nan")
        pass_pc = s["pass_without_full_coverage"] / n_partial if n_partial > 0 else float("nan")
        mean_retrieved = sum(s["retrieved_counts"]) / n

        print(f"{variant:<8} {n:>5}  {pass_rate*100:>5.1f}%  {recall:>7.3f}  {precision:>7.3f}  "
              f"{full_cov_rate*100:>8.1f}%  "
              f"{pass_fc*100:>12.1f}%  "
              f"{pass_pc*100:>12.1f}%")

        summary_rows.append({
            "model_group": label,
            "variant": variant,
            "n": n,
            "pass_rate": round(pass_rate, 4),
            "mean_recall": round(recall, 4),
            "mean_precision": round(precision, 4),
            "full_coverage_rate": round(full_cov_rate, 4),
            "pass_rate_given_full_coverage": round(pass_fc, 4) if n_full > 0 else "",
            "pass_rate_given_partial_coverage": round(pass_pc, 4) if n_partial > 0 else "",
            "n_full_coverage": n_full,
            "n_partial_coverage": n_partial,
            "mean_snippets_retrieved": round(mean_retrieved, 2),
        })

    print(f"{'='*80}")
    print("\nKey: Recall = fraction of required snippets retrieved (mean per run)")
    print("     FullCov% = % of runs where ALL required snippets were retrieved")
    print("     Pass|FullCov = pass rate when all required snippets were retrieved")
    print("     Pass|Partial = pass rate when ≥1 required snippet was missing\n")

    return summary_rows


def main():
    parser = argparse.ArgumentParser(description="Analyze retrieval quality from batch_1 runs.")
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
        print(f"  Loaded {len(haiku_rows)} ok rows.", file=sys.stderr)
        all_summary += analyze(haiku_rows, signal_only=signal_only, label="Haiku (claude-haiku-4-5)")

    if args.model in ("codex", "all"):
        print("Loading Codex runs...", file=sys.stderr)
        codex_rows = load_csvs(CODEX_DIRS)
        print(f"  Loaded {len(codex_rows)} ok rows.", file=sys.stderr)
        all_summary += analyze(codex_rows, signal_only=False, label="Codex (gpt-5.1-codex-mini, all bugs)")

    # Write CSV
    OUTPUT_DIR.mkdir(exist_ok=True)
    out_path = OUTPUT_DIR / "retrieval_quality.csv"
    if all_summary:
        fieldnames = list(all_summary[0].keys())
        with open(out_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(all_summary)
        print(f"Wrote {out_path}")


if __name__ == "__main__":
    main()
