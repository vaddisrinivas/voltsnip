#!/usr/bin/env python3
"""Recompute Haiku pytest pass rates using ONLY the 3 batch_1 runs."""

import json
from collections import defaultdict
from pathlib import Path

RUNS = [
    Path("/Users/srinivasvaddi/moltsnip/vsevals/vsevals_runs/batch_1/matrix_20260303T193221340869Z"),
    Path("/Users/srinivasvaddi/moltsnip/vsevals/vsevals_runs/batch_1/matrix_20260303T201709883387Z"),
    Path("/Users/srinivasvaddi/moltsnip/vsevals/vsevals_runs/batch_1/matrix_20260303T215606747051Z"),
]

NOISY_BUGS = {"BUG41", "BUG59", "BUG62", "BUG68"}
ALL_BUGS = {f"BUG{i}" for i in range(41, 71)}
SIGNAL_BUGS = ALL_BUGS - NOISY_BUGS

VARIANTS = ["P0", "P1", "P2", "P3", "P4", "P5", "P6"]


def load_run(run_dir: Path) -> list:
    """Load all full_dump.json from a matrix run."""
    cells = []
    runs_dir = run_dir / "runs"
    if not runs_dir.exists():
        print(f"WARNING: {runs_dir} does not exist")
        return cells
    for cell_dir in sorted(runs_dir.iterdir()):
        dump_path = cell_dir / "full_dump.json"
        if not dump_path.exists():
            continue
        with open(dump_path) as f:
            d = json.load(f)
        task_id = (d.get("task_id") or "").upper()
        variant_id = (d.get("variant_id") or "").upper()
        pytest_result = d.get("pytest_result") or {}
        pytest_passed = pytest_result.get("passed", False)
        pytest_ran = pytest_result.get("ran", False)
        cells.append({
            "task_id": task_id,
            "variant_id": variant_id,
            "pytest_passed": bool(pytest_passed),
            "pytest_ran": bool(pytest_ran),
        })
    return cells


def fmt_frac(p, t):
    if t == 0:
        return "---"
    return f"{p}/{t}"


def main():
    # Collect all data
    all_data = []
    for i, run_dir in enumerate(RUNS):
        run_label = run_dir.name
        cells = load_run(run_dir)
        print(f"Run {i+1} ({run_label}): {len(cells)} cells loaded")
        all_data.append((i, run_label, cells))

    print()

    # Structure: variant -> run_idx -> [passed, total]
    variant_run_signal = defaultdict(lambda: defaultdict(lambda: [0, 0]))
    variant_run_all = defaultdict(lambda: defaultdict(lambda: [0, 0]))

    for run_idx, run_label, cells in all_data:
        for c in cells:
            tid = c["task_id"]
            vid = c["variant_id"]
            if tid not in ALL_BUGS:
                continue
            if vid not in VARIANTS:
                continue

            # All bugs
            variant_run_all[vid][run_idx][1] += 1
            if c["pytest_passed"]:
                variant_run_all[vid][run_idx][0] += 1

            # Signal bugs only
            if tid in SIGNAL_BUGS:
                variant_run_signal[vid][run_idx][1] += 1
                if c["pytest_passed"]:
                    variant_run_signal[vid][run_idx][0] += 1

    # ── Per-variant, per-run breakdown on SIGNAL bugs ──
    print("=" * 100)
    print("PER-RUN BREAKDOWN -- SIGNAL BUGS ONLY (26 bugs)")
    print("=" * 100)

    print(f"{'Variant':<10}  {'Run1 pass/tot':>14}  {'Run2 pass/tot':>14}  {'Run3 pass/tot':>14}  {'TOTAL pass/tot':>16}  {'Rate':>8}")
    print("-" * 100)

    for v in VARIANTS:
        total_passed = 0
        total_count = 0
        parts = [f"{v:<10}"]
        for i in range(3):
            p, t = variant_run_signal[v][i]
            total_passed += p
            total_count += t
            parts.append(f"{fmt_frac(p, t):>14}")
        rate = (total_passed / total_count * 100) if total_count > 0 else 0
        parts.append(f"{fmt_frac(total_passed, total_count):>16}")
        parts.append(f"{rate:>7.1f}%")
        print("  ".join(parts))

    print()
    print("=" * 100)
    print("PER-RUN BREAKDOWN -- ALL 30 BUGS")
    print("=" * 100)

    print(f"{'Variant':<10}  {'Run1 pass/tot':>14}  {'Run2 pass/tot':>14}  {'Run3 pass/tot':>14}  {'TOTAL pass/tot':>16}  {'Rate':>8}")
    print("-" * 100)

    for v in VARIANTS:
        total_passed = 0
        total_count = 0
        parts = [f"{v:<10}"]
        for i in range(3):
            p, t = variant_run_all[v][i]
            total_passed += p
            total_count += t
            parts.append(f"{fmt_frac(p, t):>14}")
        rate = (total_passed / total_count * 100) if total_count > 0 else 0
        parts.append(f"{fmt_frac(total_passed, total_count):>16}")
        parts.append(f"{rate:>7.1f}%")
        print("  ".join(parts))

    print()
    print("=" * 100)
    print("SUMMARY TABLE (for paper) -- 3 Haiku batch_1 runs only")
    print("=" * 100)
    print(f"{'Variant':<10}  {'Signal(26) Rate':>16}  {'All(30) Rate':>14}")
    print("-" * 50)
    for v in VARIANTS:
        sig_p = sum(variant_run_signal[v][i][0] for i in range(3))
        sig_t = sum(variant_run_signal[v][i][1] for i in range(3))
        all_p = sum(variant_run_all[v][i][0] for i in range(3))
        all_t = sum(variant_run_all[v][i][1] for i in range(3))
        sig_rate = (sig_p / sig_t * 100) if sig_t > 0 else 0
        all_rate = (all_p / all_t * 100) if all_t > 0 else 0
        print(f"{v:<10}  {sig_rate:>15.1f}%  {all_rate:>13.1f}%")

    # ── Per-bug detail for P0 (to verify signal vs noisy classification) ──
    print()
    print("=" * 100)
    print("P0 PER-BUG DETAIL (verify signal classification)")
    print("=" * 100)
    p0_bug = defaultdict(lambda: [0, 0])  # bug -> [passed, total]
    for run_idx, run_label, cells in all_data:
        for c in cells:
            if c["variant_id"] == "P0" and c["task_id"] in ALL_BUGS:
                p0_bug[c["task_id"]][1] += 1
                if c["pytest_passed"]:
                    p0_bug[c["task_id"]][0] += 1

    for bug in sorted(p0_bug.keys(), key=lambda x: int(x.replace("BUG", ""))):
        p, t = p0_bug[bug]
        label = "NOISY" if bug in NOISY_BUGS else "signal"
        rate = (p / t * 100) if t > 0 else 0
        print(f"  {bug:<8}  {p}/{t}  ({rate:5.1f}%)  [{label}]")


if __name__ == "__main__":
    main()
