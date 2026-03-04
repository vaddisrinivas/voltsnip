#!/usr/bin/env python3
"""
Analyse the 3 Haiku batch_1 runs for Script30.

Outputs:
  1. ALL-BUGS (30) pass rates per variant (pooled across 3 runs)
  2. P0 per-bug pass counts (to identify noisy bugs)
  3. Per-run signal-bug pass rates per variant (for variance table)
"""

import csv
import statistics
from collections import defaultdict
from pathlib import Path

# -------------------------------------------------------------------
# Config
# -------------------------------------------------------------------
RUN_DIRS = [
    Path("vsevals_runs/batch_1/matrix_20260303T193221340869Z"),
    Path("vsevals_runs/batch_1/matrix_20260303T201709883387Z"),
    Path("vsevals_runs/batch_1/matrix_20260303T215606747051Z"),
]

VARIANTS = ["P0", "P1", "P2", "P3", "P4", "P5", "P6"]
ALL_BUGS = [f"BUG{i}" for i in range(41, 71)]  # 30 bugs

# Noisy bugs from prior 4-run analysis (P0 stochastic)
NOISY_BUGS = {"BUG41", "BUG59", "BUG62", "BUG68"}
SIGNAL_BUGS = sorted(set(ALL_BUGS) - NOISY_BUGS)

# -------------------------------------------------------------------
# Load data
# -------------------------------------------------------------------

def load_run(run_dir: Path) -> list[dict]:
    csv_path = run_dir / "matrix_results.csv"
    if not csv_path.exists():
        raise FileNotFoundError(csv_path)
    with open(csv_path) as f:
        return list(csv.DictReader(f))


def pytest_passed(row: dict) -> bool:
    return row.get("pytest_passed", "").strip().lower() == "true"


runs_data = []
for d in RUN_DIRS:
    rows = load_run(d)
    runs_data.append(rows)
    print(f"Loaded {len(rows)} cells from {d.name}")

print()

# -------------------------------------------------------------------
# 1. ALL-BUGS pass rates per variant (pooled)
# -------------------------------------------------------------------
print("=" * 70)
print("1) ALL-BUGS (30 bugs) pass rates per variant -- pooled across 3 runs")
print("=" * 70)

variant_total = defaultdict(int)
variant_passed = defaultdict(int)

for rows in runs_data:
    for r in rows:
        v = r["variant_id"]
        variant_total[v] += 1
        if pytest_passed(r):
            variant_passed[v] += 1

print(f"\n{'Variant':<10} {'Passed':>8} {'Total':>8} {'Rate':>10}")
print("-" * 40)
for v in VARIANTS:
    p = variant_passed[v]
    t = variant_total[v]
    rate = p / t * 100 if t else 0
    print(f"{v:<10} {p:>8} {t:>8} {rate:>9.1f}%")

print()

# -------------------------------------------------------------------
# 2. P0 per-bug pass counts across 3 runs
# -------------------------------------------------------------------
print("=" * 70)
print("2) P0 pass count per bug across 3 runs (identifies noisy bugs)")
print("=" * 70)

bug_p0_passes = defaultdict(int)
bug_p0_total = defaultdict(int)

for rows in runs_data:
    for r in rows:
        if r["variant_id"] == "P0":
            bug = r["task_id"]
            bug_p0_total[bug] += 1
            if pytest_passed(r):
                bug_p0_passes[bug] += 1

print(f"\n{'Bug':<10} {'Passes':>8} {'/ Runs':>8}  {'Classification'}")
print("-" * 50)
noisy_found = []
for bug in ALL_BUGS:
    p = bug_p0_passes[bug]
    t = bug_p0_total[bug]
    if p > 0 and p < t:
        label = "** NOISY **"
        noisy_found.append(bug)
    elif p == t and t > 0:
        label = "** LEAKY (all pass) **"
        noisy_found.append(bug)
    elif p == 0:
        label = "signal"
    else:
        label = "?"
    print(f"{bug:<10} {p:>8} {'/ ' + str(t):>8}  {label}")

print(f"\nNoisy/leaky bugs (P0 passes > 0): {noisy_found if noisy_found else 'NONE'}")
signal_from_data = sorted(set(ALL_BUGS) - set(noisy_found))
print(f"Signal bugs ({len(signal_from_data)}): {signal_from_data}")

print()

# -------------------------------------------------------------------
# 3. Per-run signal-bug pass rates per variant (variance table)
# -------------------------------------------------------------------
print("=" * 70)
print("3) Per-run signal-bug pass rates per variant (for variance table)")
print(f"   Signal set = {len(SIGNAL_BUGS)} bugs (excluding {sorted(NOISY_BUGS)})")
print("=" * 70)

run_variant_passed = []
run_variant_total = []

for rows in runs_data:
    vp = defaultdict(int)
    vt = defaultdict(int)
    for r in rows:
        if r["task_id"] in set(SIGNAL_BUGS):
            v = r["variant_id"]
            vt[v] += 1
            if pytest_passed(r):
                vp[v] += 1
    run_variant_passed.append(vp)
    run_variant_total.append(vt)

header = f"{'Variant':<10}"
for i in range(len(RUN_DIRS)):
    header += f" {'Run ' + str(i+1):>12}"
header += f" {'Mean':>12} {'Std':>10}"
print(f"\n{header}")
print("-" * len(header))

for v in VARIANTS:
    line = f"{v:<10}"
    rates = []
    for i in range(len(RUN_DIRS)):
        p = run_variant_passed[i][v]
        t = run_variant_total[i][v]
        rate = p / t * 100 if t else 0
        rates.append(rate)
        line += f" {rate:>10.1f}% "
    mean = statistics.mean(rates)
    std = statistics.stdev(rates) if len(rates) > 1 else 0
    line += f" {mean:>9.1f}%  {std:>7.1f}%"
    print(line)

print()

# -------------------------------------------------------------------
# Bonus: Per-run ALL-BUGS for completeness
# -------------------------------------------------------------------
print("=" * 70)
print("   (Bonus) Per-run ALL-BUGS (30) pass rates per variant")
print("=" * 70)

run_all_passed = []
run_all_total = []

for rows in runs_data:
    vp = defaultdict(int)
    vt = defaultdict(int)
    for r in rows:
        v = r["variant_id"]
        vt[v] += 1
        if pytest_passed(r):
            vp[v] += 1
    run_all_passed.append(vp)
    run_all_total.append(vt)

header = f"{'Variant':<10}"
for i in range(len(RUN_DIRS)):
    header += f" {'Run ' + str(i+1):>12}"
header += f" {'Mean':>12} {'Std':>10}"
print(f"\n{header}")
print("-" * len(header))

for v in VARIANTS:
    line = f"{v:<10}"
    rates = []
    for i in range(len(RUN_DIRS)):
        p = run_all_passed[i][v]
        t = run_all_total[i][v]
        rate = p / t * 100 if t else 0
        rates.append(rate)
        line += f" {rate:>10.1f}% "
    mean = statistics.mean(rates)
    std = statistics.stdev(rates) if len(rates) > 1 else 0
    line += f" {mean:>9.1f}%  {std:>7.1f}%"
    print(line)

print()
