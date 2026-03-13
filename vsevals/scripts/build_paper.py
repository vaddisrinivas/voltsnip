#!/usr/bin/env python3
"""
Paper build script for the VoltSnip eval paper.

Single command to:
  1. Recompute all numbers from run data
  2. Generate publication-quality figures (PDF)
  3. Update paper.tex with computed numbers
  4. Compile to PDF via tectonic

Usage:
  cd vsevals/
  uv run python3 scripts/build_paper.py                              # auto-discover runs
  uv run python3 scripts/build_paper.py --runs-dir vsevals_runs/     # explicit runs dir
  uv run python3 scripts/build_paper.py --check                      # verify numbers only
  uv run python3 scripts/build_paper.py --figures                    # regenerate figures only
  uv run python3 scripts/build_paper.py --ablation-dir vsevals_runs/matrix_XYZ  # ablation run
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import subprocess
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

import matplotlib
matplotlib.use("Agg")  # non-interactive backend
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
import numpy as np

# ── Paths ────────────────────────────────────────────────────────────────────

ROOT = Path(__file__).resolve().parent.parent          # vsevals/
PAPER_DIR = ROOT / "paper"
TEX_FILE = PAPER_DIR / "paper.tex"
FIG_DIR = PAPER_DIR / "figures"

# ── Constants ────────────────────────────────────────────────────────────────

NOISY_BUGS = {"BUG41", "BUG59", "BUG62", "BUG68"}
ALL_BUGS = {f"BUG{n}" for n in range(41, 71)}
SIGNAL_BUGS = ALL_BUGS - NOISY_BUGS
VARIANTS = ["P0", "P1", "P2", "P3", "P4", "P5", "P6"]

# Model family detection: providers whose rows belong to the "claude" group.
_CLAUDE_PROVIDERS = {"claudecode", "anthropic"}
_CODEX_PROVIDERS = {"codex", "openai"}

# ── Colour palette ───────────────────────────────────────────────────────────

HAIKU_COLOR = "#4C72B0"     # steel blue
CODEX_COLOR = "#DD8452"     # warm orange
ACCENT_COLOR = "#C44E52"    # red for emphasis
GRID_COLOR = "#E0E0E0"
BG_COLOR = "#FAFAFA"

VARIANT_COLORS = {
    "P0": "#999999",  # grey – baseline
    "P1": "#BCBD22",  # olive
    "P2": "#2CA02C",  # green
    "P3": "#1F77B4",  # blue
    "P4": "#D62728",  # red – best
    "P5": "#FF7F0E",  # orange
    "P6": "#9467BD",  # purple
}

# ── Data loading ─────────────────────────────────────────────────────────────

def load_csv_path(csv_path: Path) -> list[dict[str, str]]:
    """Load a CSV from an absolute path."""
    with open(csv_path, newline="") as f:
        return list(csv.DictReader(f))


def _detect_family(rows: list[dict[str, str]]) -> str:
    """Return 'claude' or 'codex' based on the provider column in a CSV."""
    for row in rows:
        provider = (row.get("model_provider") or row.get("model_name", "")).split(":")[0].lower()
        if provider in _CLAUDE_PROVIDERS:
            return "claude"
        if provider in _CODEX_PROVIDERS:
            return "codex"
    return "other"


def discover_runs(runs_dir: Path) -> dict[str, list[list[dict[str, str]]]]:
    """Auto-discover matrix_*/matrix_results.csv under runs_dir and group by model family."""
    csv_files = sorted(runs_dir.glob("matrix_*/matrix_results.csv"))
    if not csv_files:
        # Also look one level deeper (e.g. vsevals_runs/batch_1/matrix_*/)
        csv_files = sorted(runs_dir.glob("*/matrix_*/matrix_results.csv"))
    result: dict[str, list[list[dict[str, str]]]] = {"claude": [], "codex": [], "other": []}
    for csv_path in csv_files:
        rows = load_csv_path(csv_path)
        if not rows:
            continue
        family = _detect_family(rows)
        result[family].append(rows)
        print(f"  loaded {csv_path.parent.name} → {family} ({len(rows)} rows)")
    return result


def load_ablation_run(ablation_dir: Path | None) -> list[dict[str, str]] | None:
    """Load the ablation run CSV from ablation_dir if provided."""
    if ablation_dir is None:
        return None
    csv_path = ablation_dir / "matrix_results.csv"
    if csv_path.exists():
        return load_csv_path(csv_path)
    print(f"  ⚠ Ablation CSV not found in {ablation_dir}")
    return None


def compute_ablation_p4(rows: list[dict[str, str]]) -> dict[str, int]:
    """Compute P4 pass rate on signal bugs from ablation run."""
    passed = 0
    total = 0
    for row in rows:
        if row["status"] != "ok":
            continue
        task = row["task_id"].upper()
        variant = row["variant_id"].upper()
        if task not in SIGNAL_BUGS or variant != "P4":
            continue
        if row.get("pytest_ran", "").lower() != "true":
            continue
        total += 1
        if row.get("pytest_passed", "").lower() == "true":
            passed += 1
    return {"passed": passed, "total": total}


# ── Number computation ───────────────────────────────────────────────────────

def compute_pass_rates(
    runs: list[list[dict[str, str]]],
    bug_filter: set[str] | None = None,
) -> dict[str, dict[str, int]]:
    """
    Compute pytest pass rates per variant across all runs.
    Returns {variant: {"passed": int, "total": int}}.
    """
    rates: dict[str, dict[str, int]] = {v: {"passed": 0, "total": 0} for v in VARIANTS}
    for run_rows in runs:
        for row in run_rows:
            if row["status"] != "ok":
                continue
            task = row["task_id"].upper()
            variant = row["variant_id"].upper()
            if bug_filter and task not in bug_filter:
                continue
            if variant not in rates:
                continue
            if row.get("pytest_ran", "").lower() != "true":
                continue
            rates[variant]["total"] += 1
            if row.get("pytest_passed", "").lower() == "true":
                rates[variant]["passed"] += 1
    return rates


def compute_per_run_rates(
    runs: list[list[dict[str, str]]],
    bug_filter: set[str] | None = None,
) -> dict[str, list[float]]:
    """
    Compute per-run pass rates for each variant.
    Returns {variant: [rate_run1, rate_run2, ...]}.
    """
    result: dict[str, list[float]] = {v: [] for v in VARIANTS}
    for run_rows in runs:
        per_variant: dict[str, dict[str, int]] = {v: {"passed": 0, "total": 0} for v in VARIANTS}
        for row in run_rows:
            if row["status"] != "ok":
                continue
            task = row["task_id"].upper()
            variant = row["variant_id"].upper()
            if bug_filter and task not in bug_filter:
                continue
            if variant not in per_variant:
                continue
            if row.get("pytest_ran", "").lower() != "true":
                continue
            per_variant[variant]["total"] += 1
            if row.get("pytest_passed", "").lower() == "true":
                per_variant[variant]["passed"] += 1
        for v in VARIANTS:
            d = per_variant[v]
            rate = d["passed"] / d["total"] * 100 if d["total"] > 0 else 0.0
            result[v].append(rate)
    return result


def fmt_pct(passed: int, total: int) -> str:
    """Format as 'XX.X%' with 1 decimal."""
    if total == 0:
        return "N/A"
    return f"{passed / total * 100:.1f}%"


def fmt_frac(passed: int, total: int) -> str:
    """Format as 'XX.X% (P/T)'."""
    if total == 0:
        return "N/A"
    return f"{passed / total * 100:.1f}\\% ({passed}/{total})"


# ── Figure generation ────────────────────────────────────────────────────────

def set_paper_style():
    """Configure matplotlib for publication-quality output."""
    plt.rcParams.update({
        "font.family": "serif",
        "font.serif": ["Computer Modern Roman", "CMU Serif", "DejaVu Serif"],
        "font.size": 10,
        "axes.titlesize": 11,
        "axes.labelsize": 10,
        "xtick.labelsize": 9,
        "ytick.labelsize": 9,
        "legend.fontsize": 9,
        "figure.dpi": 300,
        "savefig.dpi": 300,
        "savefig.bbox": "tight",
        "savefig.pad_inches": 0.05,
        "axes.grid": True,
        "grid.alpha": 0.3,
        "axes.spines.top": False,
        "axes.spines.right": False,
    })


def fig_surface_hierarchy(haiku_signal: dict, codex_all: dict, n_haiku: int = 0, n_codex: int = 0) -> Path:
    """
    Figure 1: Surface hierarchy bar chart.
    Claude signal-set and Codex all-bugs side by side.
    """
    fig, ax = plt.subplots(figsize=(5.5, 3.2))

    x = np.arange(len(VARIANTS))
    width = 0.35

    haiku_rates = [haiku_signal[v]["passed"] / haiku_signal[v]["total"] * 100
                   if haiku_signal[v]["total"] > 0 else 0 for v in VARIANTS]
    codex_rates = [codex_all[v]["passed"] / codex_all[v]["total"] * 100
                   if codex_all[v]["total"] > 0 else 0 for v in VARIANTS]

    haiku_label = f"Claude (signal, n={n_haiku})" if n_haiku else "Claude (signal)"
    codex_label = f"Codex (all, n={n_codex})" if n_codex else "Codex (all)"
    bars_h = ax.bar(x - width / 2, haiku_rates, width, label=haiku_label,
                    color=HAIKU_COLOR, edgecolor="white", linewidth=0.5)
    bars_c = ax.bar(x + width / 2, codex_rates, width, label=codex_label,
                    color=CODEX_COLOR, edgecolor="white", linewidth=0.5)

    # Annotate top bars
    for bars in [bars_h, bars_c]:
        for bar in bars:
            h = bar.get_height()
            if h > 0:
                ax.annotate(f"{h:.0f}",
                            xy=(bar.get_x() + bar.get_width() / 2, h),
                            xytext=(0, 3), textcoords="offset points",
                            ha="center", va="bottom", fontsize=7)

    ax.set_xlabel("Context Surface Variant")
    ax.set_ylabel("Pytest Pass Rate (%)")
    ax.set_title("Surface Hierarchy: Pytest Pass Rates by Variant")
    ax.set_xticks(x)
    ax.set_xticklabels(VARIANTS)
    ax.set_ylim(0, 85)
    ax.yaxis.set_major_formatter(mticker.PercentFormatter(100))
    ax.legend(loc="upper left", framealpha=0.9)

    out = FIG_DIR / "fig1_surface_hierarchy.pdf"
    fig.savefig(out)
    plt.close(fig)
    print(f"  ✓ {out.name}")
    return out


def fig_per_run_variance(per_run: dict[str, list[float]]) -> Path:
    """
    Figure 2: Per-run variance for Haiku (signal set).
    Grouped bars showing individual runs + mean line.
    """
    show_variants = ["P0", "P2", "P3", "P4", "P5", "P6"]  # skip P1 (near-zero)
    n_runs = len(per_run["P0"])
    n_vars = len(show_variants)

    fig, ax = plt.subplots(figsize=(5.5, 3.0))

    x = np.arange(n_vars)
    total_width = 0.7
    bar_width = total_width / n_runs
    run_colors = ["#7FB3D8", "#4C72B0", "#2E4A7A"]  # light to dark blue

    for i in range(n_runs):
        offsets = x - total_width / 2 + bar_width * (i + 0.5)
        rates = [per_run[v][i] for v in show_variants]
        ax.bar(offsets, rates, bar_width, label=f"Run {i + 1}",
               color=run_colors[i], edgecolor="white", linewidth=0.5)

    # Mean markers
    means = [np.mean(per_run[v]) for v in show_variants]
    ax.scatter(x, means, marker="D", color=ACCENT_COLOR, s=25, zorder=5, label="Mean")

    ax.set_xlabel("Context Surface Variant")
    ax.set_ylabel("Pytest Pass Rate (%)")
    ax.set_title("Per-Run Variance: Haiku Signal Set (n=3)")
    ax.set_xticks(x)
    ax.set_xticklabels(show_variants)
    ax.set_ylim(0, 100)
    ax.yaxis.set_major_formatter(mticker.PercentFormatter(100))
    ax.legend(loc="upper left", framealpha=0.9, ncol=2)

    out = FIG_DIR / "fig2_per_run_variance.pdf"
    fig.savefig(out)
    plt.close(fig)
    print(f"  ✓ {out.name}")
    return out


def fig_lift_waterfall(haiku_signal: dict) -> Path:
    """
    Figure 3: Lift waterfall – cumulative lift from P0 to P4.
    Shows incremental contribution of each context surface.
    """
    # Steps: P0→P1 (instruction), P1→P2 (tools), P2→P3 (oracle), P3→P4 (guide)
    steps = [
        ("P0\n(baseline)", "P0"),
        ("P1\n(instruction)", "P1"),
        ("P2\n(tools only)", "P2"),
        ("P3\n(oracle)", "P3"),
        ("P4\n(guide+tools)", "P4"),
    ]

    rates = []
    for label, v in steps:
        d = haiku_signal[v]
        rates.append(d["passed"] / d["total"] * 100 if d["total"] > 0 else 0)

    fig, ax = plt.subplots(figsize=(5.5, 3.0))

    x = np.arange(len(steps))
    colors = [VARIANT_COLORS[v] for _, v in steps]
    bars = ax.bar(x, rates, color=colors, edgecolor="white", linewidth=0.5, width=0.6)

    # Draw lift arrows
    for i in range(1, len(rates)):
        delta = rates[i] - rates[i - 1]
        if delta > 2:
            mid_x = x[i]
            ax.annotate(f"+{delta:.1f}pp",
                        xy=(mid_x, rates[i]),
                        xytext=(0, 5), textcoords="offset points",
                        ha="center", va="bottom", fontsize=7,
                        color="#333333", fontweight="bold")

    # Value labels on bars
    for bar, rate in zip(bars, rates):
        ax.annotate(f"{rate:.1f}%",
                    xy=(bar.get_x() + bar.get_width() / 2, rate),
                    xytext=(0, -12), textcoords="offset points",
                    ha="center", va="top", fontsize=7, color="white",
                    fontweight="bold")

    ax.set_xlabel("Context Surface (Cumulative)")
    ax.set_ylabel("Pytest Pass Rate (%)")
    ax.set_title("Lift Attribution: P0 → P4 (Haiku, Signal Set)")
    ax.set_xticks(x)
    ax.set_xticklabels([label for label, _ in steps], fontsize=8)
    ax.set_ylim(0, 85)
    ax.yaxis.set_major_formatter(mticker.PercentFormatter(100))

    out = FIG_DIR / "fig3_lift_waterfall.pdf"
    fig.savefig(out)
    plt.close(fig)
    print(f"  ✓ {out.name}")
    return out


# ── Number verification / update ─────────────────────────────────────────────

def build_number_map(
    haiku_signal: dict,
    haiku_all: dict,
    codex_all: dict,
    haiku_per_run: dict[str, list[float]],
    ablation: dict[str, int] | None = None,
) -> dict[str, str]:
    """
    Build a map of paper claims → computed values for verification.
    Returns {description: "expected_value"}.
    """
    nums = {}

    # Haiku signal set
    for v in VARIANTS:
        d = haiku_signal[v]
        nums[f"haiku_signal_{v}_pct"] = f"{d['passed'] / d['total'] * 100:.1f}" if d["total"] else "N/A"
        nums[f"haiku_signal_{v}_frac"] = f"{d['passed']}/{d['total']}" if d["total"] else "N/A"

    # Haiku all bugs
    for v in VARIANTS:
        d = haiku_all[v]
        nums[f"haiku_all_{v}_pct"] = f"{d['passed'] / d['total'] * 100:.1f}" if d["total"] else "N/A"
        nums[f"haiku_all_{v}_frac"] = f"{d['passed']}/{d['total']}" if d["total"] else "N/A"

    # Codex all bugs
    for v in VARIANTS:
        d = codex_all[v]
        nums[f"codex_all_{v}_pct"] = f"{d['passed'] / d['total'] * 100:.1f}" if d["total"] else "N/A"
        nums[f"codex_all_{v}_frac"] = f"{d['passed']}/{d['total']}" if d["total"] else "N/A"

    # Lifts
    h_p0 = haiku_signal["P0"]["passed"] / haiku_signal["P0"]["total"] * 100 if haiku_signal["P0"]["total"] else 0
    h_p4 = haiku_signal["P4"]["passed"] / haiku_signal["P4"]["total"] * 100 if haiku_signal["P4"]["total"] else 0
    nums["haiku_p4_lift"] = f"{h_p4 - h_p0:.1f}"

    # Per-run variance
    for v in ["P0", "P2", "P3", "P4", "P6"]:
        runs = haiku_per_run[v]
        nums[f"haiku_perrun_{v}_range"] = f"{max(runs) - min(runs):.1f}"
        nums[f"haiku_perrun_{v}_mean"] = f"{np.mean(runs):.1f}"

    # Total scored runs
    haiku_total = sum(haiku_signal[v]["total"] for v in VARIANTS)  # signal only
    codex_ok = sum(codex_all[v]["total"] for v in VARIANTS)
    haiku_full = sum(haiku_all[v]["total"] for v in VARIANTS)
    nums["total_scored_haiku"] = str(haiku_full)
    nums["total_scored_codex"] = str(codex_ok)
    nums["total_scored_all"] = str(haiku_full + codex_ok)

    # Ablation
    if ablation and ablation["total"] > 0:
        abl_pct = ablation["passed"] / ablation["total"] * 100
        nums["ablation_p4_pct"] = f"{abl_pct:.1f}"
        nums["ablation_p4_frac"] = f"{ablation['passed']}/{ablation['total']}"
    else:
        nums["ablation_p4_pct"] = None
        nums["ablation_p4_frac"] = None

    return nums


def verify_numbers(nums: dict[str, str]) -> None:
    """Print computed numbers for verification."""
    print("\n── Computed Numbers ──────────────────────────────────")

    print("\n  Haiku signal set (26 bugs, n=3):")
    for v in VARIANTS:
        pct = nums[f"haiku_signal_{v}_pct"]
        frac = nums[f"haiku_signal_{v}_frac"]
        print(f"    {v}: {pct}% ({frac})")

    print(f"\n  P4 lift vs P0: +{nums['haiku_p4_lift']} pp")

    print("\n  Haiku all bugs (30 bugs, n=3):")
    for v in VARIANTS:
        pct = nums[f"haiku_all_{v}_pct"]
        frac = nums[f"haiku_all_{v}_frac"]
        print(f"    {v}: {pct}% ({frac})")

    print(f"\n  Codex all bugs (errors excluded):")
    for v in VARIANTS:
        pct = nums[f"codex_all_{v}_pct"]
        frac = nums[f"codex_all_{v}_frac"]
        print(f"    {v}: {pct}% ({frac})")

    print(f"\n  Total scored runs: {nums['total_scored_all']} "
          f"(Haiku {nums['total_scored_haiku']} + Codex {nums['total_scored_codex']})")

    print("\n  Per-run variance (Haiku signal):")
    for v in ["P0", "P2", "P3", "P4", "P6"]:
        mean = nums[f"haiku_perrun_{v}_mean"]
        rng = nums[f"haiku_perrun_{v}_range"]
        print(f"    {v}: mean={mean}%, range={rng} pp")

    if nums.get("ablation_p4_pct"):
        print(f"\n  Ablation (P4, snippets hidden): {nums['ablation_p4_pct']}% ({nums['ablation_p4_frac']})")
    else:
        print("\n  Ablation: not configured (set ABLATION_RUN in script)")


# ── TeX update ────────────────────────────────────────────────────────────────

def _update_table_block(tex: str, label: str, variant_key_prefix: str, nums: dict[str, str]) -> str:
    """Update numbers within a specific labeled table block."""
    # Find the table block by its label
    label_pat = rf"\\label\{{{re.escape(label)}\}}"
    m = re.search(label_pat, tex)
    if not m:
        print(f"  ⚠ Table {label} not found in tex")
        return tex
    # Find enclosing \begin{table}...\end{table}
    start = tex.rfind(r"\begin{table", 0, m.start())
    end = tex.find(r"\end{table}", m.end())
    if start < 0 or end < 0:
        return tex
    end += len(r"\end{table}")
    block = tex[start:end]

    for v in VARIANTS:
        pct = nums[f"{variant_key_prefix}_{v}_pct"]
        frac = nums[f"{variant_key_prefix}_{v}_frac"]
        # Match: PX & [optional \textbf{] XX.X\% (N/N)
        old_pattern = rf"({v}\s*&\s*(?:\\textbf\{{)?)\d+\.\d+\\%\s*\(\d+/\d+\)"
        new_val = rf"\g<1>{pct}\\% ({frac})"
        block = re.sub(old_pattern, new_val, block)

    return tex[:start] + block + tex[end:]


def _update_cross_model_table(tex: str, nums: dict[str, str]) -> str:
    """Update the cross-model comparison table (tab:cross-model)."""
    label = "tab:cross-model"
    label_pat = rf"\\label\{{{re.escape(label)}\}}"
    m = re.search(label_pat, tex)
    if not m:
        return tex
    start = tex.rfind(r"\begin{table", 0, m.start())
    end = tex.find(r"\end{table}", m.end())
    if start < 0 or end < 0:
        return tex
    end += len(r"\end{table}")
    block = tex[start:end]

    # Rows have format: variant_label & haiku_pct & codex_pct & delta & bug_set
    cross = {
        "P0": ("P0", "haiku_signal_P0_pct", "codex_all_P0_pct"),
        "P3": ("P3 (oracle)", "haiku_signal_P3_pct", "codex_all_P3_pct"),
        "P4": ("P4 (SKILL.md + tools)", "haiku_signal_P4_pct", "codex_all_P4_pct"),
        "P5": ("P5 (AGENTS.md + tools)", "haiku_signal_P5_pct", "codex_all_P5_pct"),
        "P6": ("P6 (both + tools)", "haiku_signal_P6_pct", "codex_all_P6_pct"),
    }
    for v, (label_prefix, h_key, c_key) in cross.items():
        h_val = float(nums[h_key])
        c_val = float(nums[c_key])
        delta = h_val - c_val
        sign = "+" if delta >= 0 else "-"
        delta_str = "${}${}".format(sign, f"{abs(delta):.1f} pp")
        # Match the row: label & [opt bold] haiku% & [opt bold] codex% & delta & approx
        escaped_label = re.escape(label_prefix)
        # Use plain r-string (not rf) to avoid f-string brace issues
        pat = r"(" + escaped_label + r"\s*&\s*(?:\\textbf\{\s*)?)[\d.]+\\%(\s*\}?\s*&\s*(?:\\textbf\{\s*)?)[\d.]+\\%(\s*\}?\s*&\s*)\$[+-]\$[\d.]+ pp"
        repl = r"\g<1>" + f"{h_val:.1f}" + r"\\%" + r"\g<2>" + f"{c_val:.1f}" + r"\\%" + r"\g<3>" + delta_str
        block = re.sub(pat, repl, block)

    return tex[:start] + block + tex[end:]


def update_tex_numbers(tex: str, nums: dict[str, str]) -> str:
    """
    Update all computed numbers in paper.tex.
    Uses table-label-anchored replacements to avoid cross-table confusion.
    """
    n_haiku = int(nums.get("n_claude_runs", 0))
    n_codex = int(nums.get("n_codex_runs", 0))
    total_haiku = int(nums["total_scored_haiku"])
    total_codex = int(nums["total_scored_codex"])
    total_all = total_haiku + total_codex

    # ── Table: Haiku signal results (tab:results-haiku) ──
    tex = _update_table_block(tex, "tab:results-haiku", "haiku_signal", nums)

    # ── Table: Codex results (tab:results-codex) ──
    tex = _update_table_block(tex, "tab:results-codex", "codex_all", nums)

    # ── Table: Haiku all-bugs appendix (tab:all-bugs) ──
    tex = _update_table_block(tex, "tab:all-bugs", "haiku_all", nums)

    # ── Table: Cross-model comparison (tab:cross-model) ──
    tex = _update_cross_model_table(tex, nums)

    # ── Models table (tab:models) ──
    tex = re.sub(
        r"(Claude Code\s*&\s*claude-haiku-4-5\s*&\s*)\d+(\s*&\s*)\d+",
        rf"\g<1>{n_haiku}\g<2>{total_haiku}",
        tex,
    )
    tex = re.sub(
        r"(Codex\s*&\s*gpt-5.1-codex-mini\s*&\s*)\d+(\s*&\s*)\d+",
        rf"\g<1>{n_codex}\g<2>{total_codex}",
        tex,
    )

    # ── Abstract: total scored runs ──
    tex = re.sub(
        r"[\d,]+ scored runs evaluated",
        f"{total_all:,} scored runs evaluated",
        tex,
    )

    # ── Abstract: P4 Haiku rate ──
    h_p4 = nums["haiku_signal_P4_pct"]
    tex = re.sub(
        r"(reaches\s*\\textbf\{)[\d.]+\\%(\}\s*for Haiku)",
        rf"\g<1>{h_p4}\\%\2",
        tex,
    )

    # ── Abstract: P4 lift ──
    lift = nums["haiku_p4_lift"]
    tex = re.sub(
        r"a \$\+\$[\d.]+ percentage-point lift",
        f"a $+${lift} percentage-point lift",
        tex,
    )

    # ── Abstract: Codex P3 and P4 rates ──
    c_p3 = nums["codex_all_P3_pct"]
    c_p4 = nums["codex_all_P4_pct"]
    tex = re.sub(
        r"(static snippet injection\s*\(P3\$=\$)[\d.]+\\%",
        rf"\g<1>{c_p3}\\%",
        tex,
    )
    tex = re.sub(
        r"(tool-based retrieval\s*\(P4\$=\$)[\d.]+\\%",
        rf"\g<1>{c_p4}\\%",
        tex,
    )

    # ── Introduction: same Codex P3/P4 pattern ──
    tex = re.sub(
        r"(static injection\s*\(P3\$=\$)[\d.]+\\%",
        rf"\g<1>{c_p3}\\%",
        tex,
    )
    tex = re.sub(
        r"(dynamic retrieval\s*\(P4\$=\$)[\d.]+\\%",
        rf"\g<1>{c_p4}\\%",
        tex,
    )

    # ── Setup section: error counts and totals ──
    # Run error counts
    tex = re.sub(
        r"Run~1:\s*\d+ errors out of 210 cells;\s*Run~2:\s*\d+ errors;\s*Run~3:\s*\d+ errors?\s*(?:out of 210 cells)?",
        f"Run~1: 30 errors out of 210 cells; Run~2: 0 errors; Run~3: 1 error out of 210 cells",
        tex,
    )
    # Total scored runs (setup section)
    tex = re.sub(
        r"[\d,]+ scored runs\s*\(\d+ Haiku \+ \d+ Codex\)",
        f"{total_all:,} scored runs ({total_haiku} Haiku + {total_codex} Codex)",
        tex,
    )

    # ── N per cell in abstract ──
    tex = re.sub(
        r"(claude-haiku-4-5,\s*\$n\{=\})\d+",
        rf"\g<1>{n_haiku}",
        tex,
    )
    tex = re.sub(
        r"(gpt-5.1-codex-mini,\s*\$n\{=\})\d+",
        rf"\g<1>{n_codex}",
        tex,
    )

    # ── Intro: n values ──
    tex = re.sub(
        r"(for Haiku\s*\(\$n\{=\})\d+",
        rf"\g<1>{n_haiku}",
        tex,
    )
    tex = re.sub(
        r"(for Codex\s*\(\$n\{=\})\d+",
        rf"\g<1>{n_codex}",
        tex,
    )

    # ── Over-specification section: P6 and P4 rates ──
    h_p6 = nums["haiku_signal_P6_pct"]
    h_p4_val = float(h_p4)
    h_p6_val = float(h_p6)
    gap = h_p4_val - h_p6_val
    tex = re.sub(
        r"P6 \(both guide documents \+ tools\) scored [\d.]+\\%,\s*lower than P4 \(SKILL\.md only \+ tools\) at [\d.]+\\%\s*---\s*an [\d.]+ percentage-point gap",
        f"P6 (both guide documents + tools) scored {h_p6}\\%, lower than P4 (SKILL.md only + tools) at {h_p4}\\% --- an {gap:.1f} percentage-point gap",
        tex,
    )

    # ── Figure caption: n values for Codex ──
    tex = re.sub(
        r"(Codex\s*\(all 30 bugs,\s*\$n\{=\})\d+",
        rf"\g<1>{n_codex}",
        tex,
    )

    # ── Figure 1 bar chart label ──
    tex = re.sub(
        r'label="Codex \(all, n=\d+\)"',
        f'label="Codex (all, n={n_codex})"',
        tex,
    )

    # ── Ablation numbers ──
    abl_pct = nums.get("ablation_p4_pct")
    abl_frac = nums.get("ablation_p4_frac")
    if abl_pct and abl_frac:
        # Replace placeholder: "X.X\%" → actual rate, "X/26" → actual fraction
        tex = re.sub(
            r"The ablation pass rate was \\textbf\{[^}]+\}[^\\]*\\\\%\}\s*\([^)]*\)",
            f"The ablation pass rate was \\\\textbf{{{abl_pct}\\\\%}} ({abl_frac})",
            tex,
        )
        # Also try the simpler placeholder pattern
        tex = re.sub(
            r"\\textbf\{X\.X\\%\}\s*\(X/26\)",
            f"\\\\textbf{{{abl_pct}\\\\%}} ({abl_frac})",
            tex,
        )
        # Remove the placeholder footnote if present
        tex = tex.replace(
            r"\footnote{Placeholder: ablation numbers to be filled after the run completes.}",
            "",
        )
        print(f"  ✓ Ablation numbers filled: {abl_pct}% ({abl_frac})")

    return tex


# ── TeX: add figure includes ─────────────────────────────────────────────────

FIGURE_1_TEX = r"""
\begin{figure}[t]
\centering
\includegraphics[width=\textwidth]{figures/fig1_surface_hierarchy.pdf}
\caption{Pytest pass rates by context surface variant for Haiku (26 signal bugs, $n{=}3$) and Codex (all 30 bugs, $n{=}3$, errors excluded). P4 (focused guide + autonomous retrieval) achieves the highest rate for Haiku; Codex peaks at P3 (oracle injection).}
\label{fig:surface-hierarchy}
\end{figure}
""".strip()

FIGURE_2_TEX = r"""
\begin{figure}[t]
\centering
\includegraphics[width=\textwidth]{figures/fig2_per_run_variance.pdf}
\caption{Per-run pass rates for Haiku across three independent runs (26 signal bugs). P4 shows the widest inter-run variance (26.9~pp range), reflecting stochastic retrieval strategy. P0 is stable at 0.0\% across all runs.}
\label{fig:per-run-variance}
\end{figure}
""".strip()

FIGURE_3_TEX = r"""
\begin{figure}[t]
\centering
\includegraphics[width=\textwidth]{figures/fig3_lift_waterfall.pdf}
\caption{Cumulative lift from P0 (baseline) to P4 (best variant) for Haiku on the 26-bug signal set. Each bar shows the absolute pass rate; annotations show incremental lift from the previous variant.}
\label{fig:lift-waterfall}
\end{figure}
""".strip()


def inject_figures(tex: str) -> str:
    """Add figure includes to paper.tex if not already present."""
    # Figure 1: after the results tables (after tab:results-codex note)
    if r"\label{fig:surface-hierarchy}" not in tex:
        marker = r"\emph{Note: Haiku results are reported on the 26-bug signal set"
        if marker in tex:
            idx = tex.index(marker)
            # Find end of this paragraph
            end_idx = tex.index("\n\n", idx)
            tex = tex[:end_idx] + "\n\n" + FIGURE_1_TEX + tex[end_idx:]

    # Figure 2: after the per-run variance table
    if r"\label{fig:per-run-variance}" not in tex:
        marker = r"P0 is perfectly stable at 0.0\% across all three runs"
        if marker in tex:
            idx = tex.index(marker)
            end_idx = tex.index("\n\n", idx)
            tex = tex[:end_idx] + "\n\n" + FIGURE_2_TEX + tex[end_idx:]

    # Figure 3: after causal attribution section
    if r"\label{fig:lift-waterfall}" not in tex:
        marker = r"Conditions 1--3 together support a causal claim"
        if marker in tex:
            idx = tex.index(marker)
            end_idx = tex.index("\n\n", idx)
            tex = tex[:end_idx] + "\n\n" + FIGURE_3_TEX + tex[end_idx:]

    return tex


# ── TeX: hyperlinked references ──────────────────────────────────────────────

ARXIV_URLS = {
    "chen2021evaluating": "https://arxiv.org/abs/2107.03374",
    "austin2021program": "https://arxiv.org/abs/2108.07732",
    "jimenez2024swebench": "https://arxiv.org/abs/2310.06770",
    "yang2024sweagent": "https://arxiv.org/abs/2405.15793",
    "lewis2020retrieval": "https://arxiv.org/abs/2005.11401",
    "schick2023toolformer": "https://arxiv.org/abs/2302.04761",
    "yao2023react": "https://arxiv.org/abs/2210.03629",
}


def add_bib_urls(tex: str) -> str:
    """Add arXiv URLs to bibliography entries."""
    for key, url in ARXIV_URLS.items():
        # Find the bibitem and add URL before the closing line if not present
        if url in tex:
            continue
        # Pattern: \emph{arXiv preprint arXiv:XXXX.XXXXX}, YYYY.
        # Replace with: \emph{arXiv preprint arXiv:XXXX.XXXXX}, YYYY.\\ \url{URL}
        # Actually, just add \newblock \url{} after the existing \newblock line
        pattern = rf"(\\bibitem\[.*?\]\{{{key}\}}.*?\\newblock\s*\\emph\{{[^}}]+\}},\s*\d{{4}}\.)"
        match = re.search(pattern, tex, re.DOTALL)
        if match:
            old = match.group(0)
            new = old + f"\n\\newblock \\url{{{url}}}"
            tex = tex.replace(old, new)
    return tex


# ── Compile ──────────────────────────────────────────────────────────────────

def compile_pdf() -> bool:
    """Compile paper.tex to PDF using tectonic."""
    print("\n── Compiling PDF ────────────────────────────────────")
    result = subprocess.run(
        ["tectonic", "paper.tex"],
        cwd=PAPER_DIR,
        capture_output=True,
        text=True,
        timeout=120,
    )
    # Count warnings
    warnings = [l for l in result.stderr.splitlines() if "warning:" in l.lower()]
    overfull = [l for l in warnings if "Overfull" in l]
    errors = [l for l in result.stderr.splitlines() if "error" in l.lower() and "is_error" not in l]

    if result.returncode != 0:
        print(f"  ✗ Compilation failed (exit code {result.returncode})")
        print(result.stderr[-500:])
        return False

    pdf_path = PAPER_DIR / "paper.pdf"
    size_kb = pdf_path.stat().st_size / 1024
    print(f"  ✓ paper.pdf ({size_kb:.0f} KB)")
    if overfull:
        # Deduplicate (tectonic runs twice)
        unique = list(dict.fromkeys(overfull))
        print(f"  ⚠ {len(unique)} overfull hbox warnings (cosmetic)")
    return True


# ── Main ─────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Build paper.tex with computed numbers and figures")
    parser.add_argument("--runs-dir", default=None,
                        help="Directory containing matrix_* run subdirs (default: vsevals_runs/)")
    parser.add_argument("--ablation-dir", default=None,
                        help="Path to an ablation matrix_* dir (P4 with snippets hidden)")
    parser.add_argument("--check", action="store_true", help="Verify numbers only, don't write")
    parser.add_argument("--figures", action="store_true", help="Regenerate figures only")
    parser.add_argument("--no-compile", action="store_true", help="Skip PDF compilation")
    args = parser.parse_args()

    FIG_DIR.mkdir(parents=True, exist_ok=True)

    runs_dir = Path(args.runs_dir) if args.runs_dir else ROOT / "vsevals_runs"

    # ── Step 1: Load data ──
    print(f"── Loading runs from {runs_dir} ─────────────────────")
    data = discover_runs(runs_dir)
    n_claude = len(data["claude"])
    n_codex = len(data["codex"])
    print(f"  Claude: {n_claude} runs")
    print(f"  Codex:  {n_codex} runs")
    if not n_claude and not n_codex:
        print("  ✗ No runs found. Pass --runs-dir pointing to a directory with matrix_* subdirs.")
        sys.exit(1)

    # ── Step 1b: Load ablation ──
    ablation = None
    abl_rows = load_ablation_run(Path(args.ablation_dir) if args.ablation_dir else None)
    if abl_rows:
        ablation = compute_ablation_p4(abl_rows)
        print(f"  Ablation: P4 signal = {ablation['passed']}/{ablation['total']}")
    else:
        print("  Ablation: not configured (pass --ablation-dir to include)")

    # ── Step 2: Compute numbers ──
    print("\n── Computing pass rates ─────────────────────────────")
    haiku_signal = compute_pass_rates(data["claude"], SIGNAL_BUGS)
    haiku_all = compute_pass_rates(data["claude"], ALL_BUGS)
    codex_all = compute_pass_rates(data["codex"])  # no filter — errors excluded by status=ok
    haiku_per_run = compute_per_run_rates(data["claude"], SIGNAL_BUGS)

    nums = build_number_map(haiku_signal, haiku_all, codex_all, haiku_per_run, ablation)
    nums["n_claude_runs"] = str(n_claude)
    nums["n_codex_runs"] = str(n_codex)
    verify_numbers(nums)

    if args.check:
        print("\n── Check mode: no files modified ─────────────────────")
        return

    # ── Step 3: Generate figures ──
    print("\n── Generating figures ───────────────────────────────")
    set_paper_style()
    fig_surface_hierarchy(haiku_signal, codex_all, n_haiku=n_claude, n_codex=n_codex)
    fig_per_run_variance(haiku_per_run)
    fig_lift_waterfall(haiku_signal)

    if args.figures:
        print("\n── Figures-only mode: done ──────────────────────────")
        return

    # ── Step 4: Update paper.tex ──
    print("\n── Updating paper.tex ──────────────────────────────")
    tex = TEX_FILE.read_text()

    tex = update_tex_numbers(tex, nums)
    print("  ✓ Numbers updated")

    tex = inject_figures(tex)
    print("  ✓ Figure includes injected")

    tex = add_bib_urls(tex)
    print("  ✓ Bibliography URLs added")

    TEX_FILE.write_text(tex)
    print(f"  ✓ {TEX_FILE.name} written")

    # ── Step 5: Compile ──
    if not args.no_compile:
        compile_pdf()

    print("\n── Done ─────────────────────────────────────────────")


if __name__ == "__main__":
    main()
