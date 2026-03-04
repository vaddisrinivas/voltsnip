#!/usr/bin/env python3
"""
Recompute Codex pytest pass rates from 2 batch_1 runs.

For each run:
  - Read all full_dump.json files under runs/
  - Extract task_id, variant_id, status, pytest_result.passed
  - For duplicate task/variant pairs (retries), keep only the LAST cell
    (directories sort lexicographically by timestamp)
  - Compute pass rates per variant

Signal bugs (validated from Haiku n=4): BUG42-47, BUG49-57, BUG60-61, BUG63-67, BUG69-70
"""

import json
import os
from collections import defaultdict
from pathlib import Path

# ── Configuration ──────────────────────────────────────────────────────
RUNS = [
    (
        "Run1",
        Path("/Users/srinivasvaddi/moltsnip/vsevals/vsevals_runs/batch_1/"
             "matrix_20260303T193214057044Z/runs"),
    ),
    (
        "Run2",
        Path("/Users/srinivasvaddi/moltsnip/vsevals/vsevals_runs/batch_1/"
             "matrix_20260303T201241727101Z/runs"),
    ),
]

VARIANTS = ["p0", "p1", "p2", "p3", "p4", "p5", "p6"]

SIGNAL_BUGS = {
    f"bug{n}" for n in
    list(range(42, 48)) +        # 42-47
    list(range(49, 58)) +        # 49-57
    [60, 61] +
    list(range(63, 68)) +        # 63-67
    [69, 70]
}

ALL_BUGS = {f"bug{n}" for n in range(41, 71)}  # bug41-bug70


# ── Data loading ───────────────────────────────────────────────────────
def load_run(label: str, runs_dir: Path) -> dict:
    """Return {(task, variant): {status, pytest_passed}} after dedup."""
    cell_dirs = sorted(os.listdir(runs_dir))

    # Group by (task, variant) — sorted order = chronological
    tv_all: dict[tuple[str, str], list[tuple[str, dict]]] = defaultdict(list)
    for d in cell_dirs:
        parts = d.split("__")
        if len(parts) < 3:
            continue
        task = parts[1]   # e.g. "bug41"
        var  = parts[2]   # e.g. "p0"
        fp = runs_dir / d / "full_dump.json"
        if not fp.exists():
            continue
        with open(fp) as f:
            dump = json.load(f)
        status = dump.get("status", "unknown")
        pr = dump.get("pytest_result") or {}
        pytest_passed = pr.get("passed") if pr.get("ran") else None
        tv_all[(task, var)].append((d, {
            "status": status,
            "pytest_passed": pytest_passed,
            "dir": d,
        }))

    # Deduplicate: keep last cell for each (task, variant)
    deduped = {}
    for (task, var), entries in tv_all.items():
        # entries already sorted chronologically (dir name starts with timestamp)
        deduped[(task, var)] = entries[-1][1]

    return deduped


# ── Analysis ───────────────────────────────────────────────────────────
def analyze():
    run_data = {}
    for label, runs_dir in RUNS:
        run_data[label] = load_run(label, runs_dir)

    print("=" * 90)
    print("CODEX PYTEST PASS RATES — Recomputed from 2 batch_1 runs")
    print("=" * 90)

    # ── 1. Per-run breakdown ───────────────────────────────────────────
    for label in ["Run1", "Run2"]:
        data = run_data[label]
        print(f"\n{'─' * 90}")
        print(f"  {label}  (after dedup: {len(data)} cells)")
        print(f"{'─' * 90}")
        print(f"  {'Variant':<10} {'OK':>5} {'Error':>6} {'Passed':>7} {'Failed':>7} {'Rate':>8}")
        for var in VARIANTS:
            cells = {t: v for (t, v_), v in data.items() if v_ == var}
            ok = sum(1 for c in cells.values() if c["status"] == "ok")
            err = sum(1 for c in cells.values() if c["status"] != "ok")
            passed = sum(1 for c in cells.values()
                         if c["status"] == "ok" and c["pytest_passed"] is True)
            failed = sum(1 for c in cells.values()
                         if c["status"] == "ok" and c["pytest_passed"] is False)
            no_pytest = sum(1 for c in cells.values()
                           if c["status"] == "ok" and c["pytest_passed"] is None)
            rate = (passed / ok * 100) if ok > 0 else float("nan")
            extra = f"  (no-pytest: {no_pytest})" if no_pytest else ""
            print(f"  {var:<10} {ok:>5} {err:>6} {passed:>7} {failed:>7} {rate:>7.1f}%{extra}")

    # ── 2. Aggregate across both runs ──────────────────────────────────
    for bug_set_name, bug_set in [("ALL 30 bugs", ALL_BUGS), ("Signal 26 bugs", SIGNAL_BUGS)]:
        print(f"\n{'=' * 90}")
        print(f"  AGGREGATE — {bug_set_name}  (2 Codex runs combined)")
        print(f"{'=' * 90}")
        print(f"  {'Variant':<10} {'Passed':>7} {'OK cells':>9} {'Rate':>8}  | "
              f"{'Run1 P/OK':>10} {'Run2 P/OK':>10}")

        for var in VARIANTS:
            total_passed = 0
            total_ok = 0
            per_run = {}
            for label in ["Run1", "Run2"]:
                data = run_data[label]
                cells = {t: v for (t, v_), v in data.items()
                         if v_ == var and t in bug_set}
                ok = sum(1 for c in cells.values() if c["status"] == "ok")
                passed = sum(1 for c in cells.values()
                             if c["status"] == "ok" and c["pytest_passed"] is True)
                total_passed += passed
                total_ok += ok
                per_run[label] = (passed, ok)

            rate = (total_passed / total_ok * 100) if total_ok > 0 else float("nan")
            r1p, r1o = per_run["Run1"]
            r2p, r2o = per_run["Run2"]
            print(f"  {var:<10} {total_passed:>7} {total_ok:>9} {rate:>7.1f}%  | "
                  f"  {r1p:>2}/{r1o:<2}        {r2p:>2}/{r2o:<2}")

    # ── 3. Error cell details ──────────────────────────────────────────
    print(f"\n{'=' * 90}")
    print("  ERROR CELLS (status != 'ok') — per run, per variant")
    print(f"{'=' * 90}")
    for label in ["Run1", "Run2"]:
        data = run_data[label]
        err_cells = [(t, v_, c) for (t, v_), c in data.items() if c["status"] != "ok"]
        err_cells.sort()
        print(f"\n  {label}: {len(err_cells)} error cells")
        if err_cells:
            by_var = defaultdict(list)
            for t, v_, c in err_cells:
                by_var[v_].append(t)
            for var in VARIANTS:
                tasks = by_var.get(var, [])
                if tasks:
                    print(f"    {var}: {', '.join(sorted(tasks))}")

    # ── 4. Per-bug pass/fail detail (all 30, both runs) ───────────────
    print(f"\n{'=' * 90}")
    print("  PER-BUG DETAIL — pytest pass (1) / fail (0) / error (E) / no-pytest (N)")
    print(f"{'=' * 90}")
    header = f"  {'Bug':<8}"
    for var in VARIANTS:
        header += f" {var:>6}"
    print(header)
    print(f"  {'':─<8}" + "─" * (7 * len(VARIANTS)))

    for bug_n in range(41, 71):
        bug = f"bug{bug_n}"
        sig = "*" if bug in SIGNAL_BUGS else " "
        row = f"  {bug:<7}{sig}"
        for var in VARIANTS:
            results = []
            for label in ["Run1", "Run2"]:
                data = run_data[label]
                cell = data.get((bug, var))
                if cell is None:
                    results.append("?")
                elif cell["status"] != "ok":
                    results.append("E")
                elif cell["pytest_passed"] is True:
                    results.append("1")
                elif cell["pytest_passed"] is False:
                    results.append("0")
                else:
                    results.append("N")
            row += f"  {results[0]}{results[1]}   "
        print(row)

    print()
    print("  Legend: 1=pass 0=fail E=error N=no-pytest ?=missing *=signal bug")
    print("  Format: <Run1><Run2> for each variant cell")

    # ── 5. Compact summary line (for EXPERIMENT.md) ───────────────────
    print(f"\n{'=' * 90}")
    print("  SUMMARY LINE (all 30 bugs, n=2 Codex runs)")
    print(f"{'=' * 90}")
    parts = []
    for var in VARIANTS:
        total_passed = 0
        total_ok = 0
        for label in ["Run1", "Run2"]:
            data = run_data[label]
            cells = {t: v for (t, v_), v in data.items()
                     if v_ == var and t in ALL_BUGS}
            ok = sum(1 for c in cells.values() if c["status"] == "ok")
            passed = sum(1 for c in cells.values()
                         if c["status"] == "ok" and c["pytest_passed"] is True)
            total_passed += passed
            total_ok += ok
        rate = (total_passed / total_ok * 100) if total_ok > 0 else float("nan")
        parts.append(f"{var.upper()}: {rate:.1f}%")
    print(f"  {' | '.join(parts)}")

    parts_sig = []
    for var in VARIANTS:
        total_passed = 0
        total_ok = 0
        for label in ["Run1", "Run2"]:
            data = run_data[label]
            cells = {t: v for (t, v_), v in data.items()
                     if v_ == var and t in SIGNAL_BUGS}
            ok = sum(1 for c in cells.values() if c["status"] == "ok")
            passed = sum(1 for c in cells.values()
                         if c["status"] == "ok" and c["pytest_passed"] is True)
            total_passed += passed
            total_ok += ok
        rate = (total_passed / total_ok * 100) if total_ok > 0 else float("nan")
        parts_sig.append(f"{var.upper()}: {rate:.1f}%")
    print(f"  (signal 26 only) {' | '.join(parts_sig)}")


if __name__ == "__main__":
    analyze()
