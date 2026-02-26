#!/usr/bin/env python3
"""Three-phase orchestrator: full 22 tasks × P0–P6a × claudecode + openai.

All phases share one output directory so --resume works across interruptions
regardless of which phase was running when the job stopped.

Phase 1  claudecode  P0–P6a  spacing=0.5 s   free — uses Claude Code stored auth
Phase 2a openai      P0–P3   spacing=2.0 s   cheap — no tool calls
Phase 2b openai      P4–P6a  spacing=5.0 s   expensive — MCP multi-turn loop

Rough openai cost estimate (gpt-4o-mini, 22 tasks):
  P0+P1        44 cells × ~$0.0007  ≈  $0.03
  P2+P3        44 cells × ~$0.0009  ≈  $0.04
  P4+P5b+P5a  66 cells × ~$0.0017  ≈  $0.11
  P6b+P6a     44 cells × ~$0.0021  ≈  $0.09
  Total ≈ $0.27   (actual depends on prompt sizes and tool-call depth)

Usage
-----
  cd /path/to/moltsnip
  python vsevals/scripts/run_full_matrix.py \\
      --suite voltsnip-evals/suite.yaml \\
      --output-dir ./vsevals_runs

  # Dry-run: show plan only, no API calls
  python vsevals/scripts/run_full_matrix.py --suite ... --dry-run

  # Resume an interrupted run
  python vsevals/scripts/run_full_matrix.py --suite ... \\
      --resume ./vsevals_runs/matrix_20260225T120000Z_full

  # Skip a provider (e.g. if OPENAI_API_KEY not set)
  python vsevals/scripts/run_full_matrix.py --suite ... --skip-openai
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_HERE = Path(__file__).resolve().parent          # vsevals/scripts/
_VSEVALS_DIR = _HERE.parent                      # vsevals/
_REPO_ROOT = _VSEVALS_DIR.parent                 # moltsnip/
_MATRIX_SCRIPT = str(_HERE / "run_matrix.py")

# Default models
_DEFAULT_CLAUDECODE_MODEL = "claudecode:claude-sonnet-4-6"
_DEFAULT_OPENAI_MODEL = "openai:gpt-4o-mini"
_DEFAULT_JUDGE_MODEL = "openai:gpt-5-mini+anthropic:claude-sonnet-4-6"

# Phase definitions: (label, variants, spacing_seconds, provider_filter)
_PHASES = [
    ("claudecode  P0–P6a", "P0,P1,P2,P3,P4,P5b,P5a,P6b,P6a", 0.5,  "claudecode"),
    ("openai      P0–P3",  "P0,P1,P2,P3",                     2.0,  "openai"),
    ("openai      P4–P6a", "P4,P5b,P5a,P6b,P6a",              5.0,  "openai"),
]

# Rough cost model for openai (gpt-4o-mini, USD per cell)
_COST_PER_CELL = {
    "P0": 0.0007, "P1": 0.0007,
    "P2": 0.0009, "P3": 0.0009,
    "P4": 0.0017, "P5b": 0.0017, "P5a": 0.0017, "P6b": 0.0020, "P6a": 0.0022,
}


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Full 22×7×2 evaluation matrix (claudecode + openai).",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    p.add_argument("--suite", required=True,
                   help="Path to suite YAML (e.g. voltsnip-evals/suite.yaml)")
    p.add_argument("--output-dir", default="./vsevals_runs",
                   help="Root directory for run artifacts (default: ./vsevals_runs)")
    p.add_argument("--resume", default=None, metavar="PATH",
                   help="Resume from an existing matrix directory (skips completed cells).")

    # Models
    p.add_argument("--claudecode-model", default=_DEFAULT_CLAUDECODE_MODEL,
                   help=f"claudecode model string (default: {_DEFAULT_CLAUDECODE_MODEL})")
    p.add_argument("--openai-model", default=_DEFAULT_OPENAI_MODEL,
                   help=f"OpenAI model string (default: {_DEFAULT_OPENAI_MODEL})")
    p.add_argument("--judge-model", default=_DEFAULT_JUDGE_MODEL,
                   help=f"Scoring judge model (default: {_DEFAULT_JUDGE_MODEL})")

    # Task / variant filters
    p.add_argument("--tasks", default=None,
                   help="Comma-separated task IDs to run (default: all in suite)")
    p.add_argument("--variants", default=None,
                   help="Comma-separated variant IDs to run (default: P0–P6a). "
                        "Restricts all phases.")

    # Phase skip flags
    p.add_argument("--skip-claudecode", action="store_true",
                   help="Skip Phase 1 (claudecode runs)")
    p.add_argument("--skip-openai", action="store_true",
                   help="Skip Phases 2a+2b (openai runs)")

    # Tuning
    p.add_argument("--voltsnip-url", default=None,
                   help="VoltSnip API URL (default: $VOLTSNIP_BASE_URL or http://localhost:8011)")
    p.add_argument("--scoring-mode", default="llm", choices=["llm", "hybrid"])
    p.add_argument("--log-level", default="INFO", choices=["DEBUG", "INFO", "WARNING"])

    # Safety
    p.add_argument("--max-openai-cost", type=float, default=5.0,
                   help="Abort openai phases if estimated cost exceeds this (USD). Default: $5.00")
    p.add_argument("--dry-run", action="store_true",
                   help="Print the run plan and cost estimate without making any API calls.")

    return p


# ---------------------------------------------------------------------------
# Cost estimation
# ---------------------------------------------------------------------------

def _estimate_cost(n_tasks: int, variants: list[str]) -> float:
    return sum(_COST_PER_CELL.get(v, 0.001) for v in variants) * n_tasks


def _print_plan(args: argparse.Namespace, run_dir: Path, phases: list[tuple]) -> None:
    print("\n" + "=" * 60)
    print("  vsevals — full matrix run plan")
    print("=" * 60)
    print(f"  Suite:         {args.suite}")
    print(f"  Output dir:    {run_dir}")
    print(f"  claudecode:    {args.claudecode_model}")
    print(f"  openai:        {args.openai_model}")
    print(f"  Judge:         {args.judge_model}")
    print(f"  Tasks:         {args.tasks or 'all'}")
    print(f"  Variants:      {args.variants or 'P0–P6a (all)'}")
    print()
    print("  Phases:")
    for label, variants_str, spacing, provider in phases:
        skip = (provider == "claudecode" and args.skip_claudecode) or \
               (provider == "openai" and args.skip_openai)
        flag = "SKIP" if skip else f"spacing={spacing}s"
        print(f"    [{flag:^8}]  {label}")
    print()


# ---------------------------------------------------------------------------
# Phase runner
# ---------------------------------------------------------------------------

def _run_phase(
    *,
    label: str,
    model: str,
    variants: str,
    spacing: float,
    run_dir: Path,
    args: argparse.Namespace,
    python_bin: str,
) -> int:
    """Invoke run_matrix.py for one phase. Returns subprocess exit code."""
    cmd = [
        python_bin, _MATRIX_SCRIPT,
        "--suite",        args.suite,
        "--models",       model,
        "--variants",     variants,
        "--resume",       str(run_dir),
        "--judge-model",  args.judge_model,
        "--scoring-mode", args.scoring_mode,
        "--spacing",      str(spacing),
        "--log-level",    args.log_level,
    ]
    if args.tasks:
        cmd += ["--tasks", args.tasks]
    if args.voltsnip_url:
        cmd += ["--voltsnip-url", args.voltsnip_url]

    print(f"\n{'─' * 60}")
    print(f"  Phase: {label}")
    print(f"  Model: {model}  |  variants: {variants}  |  spacing: {spacing}s")
    print(f"{'─' * 60}\n")

    result = subprocess.run(cmd)
    return result.returncode


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    # Resolve paths relative to CWD
    suite_path = Path(args.suite)
    if not suite_path.exists():
        # Try relative to repo root
        candidate = _REPO_ROOT / args.suite
        if candidate.exists():
            args.suite = str(candidate)
        else:
            parser.error(f"Suite file not found: {args.suite}")

    output_dir = Path(args.output_dir)

    # Determine run directory (pre-compute so all phases share it)
    if args.resume:
        run_dir = Path(args.resume)
        if not run_dir.exists():
            parser.error(f"--resume path does not exist: {run_dir}")
    else:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        run_dir = output_dir / f"matrix_{stamp}_full"

    # Resolve variants filter
    all_variants = ["P0", "P1", "P2", "P3", "P4", "P5b", "P5a", "P6b", "P6a"]
    active_variants = (
        [v.strip() for v in args.variants.split(",") if v.strip()]
        if args.variants else all_variants
    )

    # Build active phases respecting --variants and --skip-* flags
    phases: list[tuple[str, str, float, str]] = []
    for label, variants_str, spacing, provider in _PHASES:
        if provider == "claudecode" and args.skip_claudecode:
            continue
        if provider == "openai" and args.skip_openai:
            continue
        # Intersect phase variants with user's variant filter
        phase_variants = [v for v in variants_str.split(",") if v in active_variants]
        if not phase_variants:
            continue
        phases.append((label, ",".join(phase_variants), spacing, provider))

    if not phases:
        print("All phases skipped. Nothing to do.")
        sys.exit(0)

    # OpenAI pre-flight checks
    openai_phases = [(l, v, s, p) for l, v, s, p in phases if p == "openai"]
    if openai_phases and not args.dry_run:
        if not (os.environ.get("OPENAI_API_KEY") or args.skip_openai):
            parser.error(
                "OPENAI_API_KEY environment variable is required for openai phases. "
                "Set it or use --skip-openai to run claudecode only."
            )

    # Cost estimate
    n_tasks_hint = 22  # full suite; actual count from suite YAML at runtime
    openai_variants_flat = [
        v for _, vs, _, p in phases if p == "openai" for v in vs.split(",")
    ]
    est_cost = _estimate_cost(n_tasks_hint, openai_variants_flat)

    _print_plan(args, run_dir, phases)

    if openai_phases:
        print(f"  Estimated openai cost: ~${est_cost:.2f}  "
              f"(cap: ${args.max_openai_cost:.2f}, model: {args.openai_model})")
        if est_cost > args.max_openai_cost:
            print(
                f"\n  ERROR: Estimated cost ${est_cost:.2f} exceeds --max-openai-cost "
                f"${args.max_openai_cost:.2f}. Increase the cap or use --skip-openai."
            )
            sys.exit(1)
        print()

    if args.dry_run:
        print("  --dry-run set: no API calls made.\n")
        sys.exit(0)

    # Ensure run_dir exists before any phase (run_matrix.py also does mkdir, but
    # we want all phases to share the same dir even on the very first invocation).
    run_dir.mkdir(parents=True, exist_ok=True)

    # Find python binary (prefer same env as this script)
    python_bin = sys.executable

    # ── Execute phases ────────────────────────────────────────────────────────
    t_start = time.time()
    failed_phases: list[str] = []

    for label, variants_str, spacing, provider in phases:
        model = (
            args.claudecode_model if provider == "claudecode" else args.openai_model
        )
        rc = _run_phase(
            label=label,
            model=model,
            variants=variants_str,
            spacing=spacing,
            run_dir=run_dir,
            args=args,
            python_bin=python_bin,
        )
        if rc != 0:
            print(f"\n  WARNING: Phase '{label}' exited with code {rc}. "
                  "Continuing to next phase.")
            failed_phases.append(label)

    # ── Final summary ─────────────────────────────────────────────────────────
    elapsed = time.time() - t_start
    print("\n" + "=" * 60)
    print("  All phases complete")
    print("=" * 60)
    print(f"  Output:   {run_dir}")
    print(f"  Elapsed:  {elapsed / 60:.1f} min")
    if failed_phases:
        print(f"  WARNING:  {len(failed_phases)} phase(s) had errors: {failed_phases}")
        print("  To retry failed cells, re-run with:")
        print(f"    --resume {run_dir}")
    else:
        print("  Status:   all phases exited cleanly")
    print()
    print(f"  Results CSV:  {run_dir}/matrix_results.csv")
    print(f"  Summary JSON: {run_dir}/matrix_summary.json")
    print(f"  Report MD:    {run_dir}/matrix_report.md")
    print()

    if failed_phases:
        sys.exit(1)


if __name__ == "__main__":
    main()
