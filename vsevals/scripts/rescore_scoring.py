#!/usr/bin/env python3
"""Post-hoc scoring (Pass 2): re-score completed matrix cells with an LLM judge.

Three-pass pipeline
-------------------
  Pass 1  run_matrix.py        Generate the fix + inline LLM judge score.
                                Scores are written to the CSV immediately.

  Pass 2  rescore_scoring.py   Reload full_dump.json, call a different/better judge,
                                update CSV.  ← YOU ARE HERE
                                Use --judge-model to override the judge.

  Pass 3  rescore_pytest.py    Run Docker pytest on generated_code.txt.  $0 LLM cost.

Why use Pass 2?
---------------
  • Swap judges after the fact (e.g. gpt-5-mini → gpt-5.2 ensemble) without re-generating
  • Re-score after updating constraint specs or judge prompts
  • Compare judge models on identical outputs (scientific control)
  • Backfill scores for a run whose judge keys were unavailable during Pass 1

Typical workflow
----------------
  # Pass 1 — generate + score inline
  python scripts/run_matrix.py --suite suite.yaml \\
      --models claudecode:claude-sonnet-4-6,codex:gpt-5.1-codex

  # Pass 2 — re-score with a better ensemble judge (writes matrix_results__gpt-5.2+claude-opus-4-6.csv)
  python scripts/rescore_scoring.py \\
      --matrix-dir ./vsevals_runs/matrix_20260226T120000Z \\
      --suite suite.yaml \\
      --judge-model "openai:gpt-5.2+anthropic:claude-opus-4-6"

  # Pass 2 — score only specific tasks (e.g. while full run still ongoing)
  python scripts/rescore_scoring.py \\
      --matrix-dir ./vsevals_runs/matrix_20260226T120000Z \\
      --suite suite.yaml \\
      --tasks BUG01,BUG03 --variants P0,P4

  # Pass 2 — force re-score with an upgraded judge
  python scripts/rescore_scoring.py \\
      --matrix-dir ./vsevals_runs/matrix_20260226T120000Z \\
      --suite suite.yaml \\
      --judge-model openai:gpt-5.3 --force

  # Pass 2 — override the output filename suffix (writes matrix_results__myrun.csv)
  python scripts/rescore_scoring.py \\
      --matrix-dir ./vsevals_runs/matrix_20260226T120000Z \\
      --suite suite.yaml \\
      --judge-model openai:gpt-5.3 --output-suffix myrun

  # Dry-run: list rows that would be rescored without running anything
  python scripts/rescore_scoring.py \\
      --matrix-dir ./vsevals_runs/matrix_20260226T120000Z \\
      --suite suite.yaml --dry-run
"""

from __future__ import annotations

import argparse
import csv
import json
import logging
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any


def _git_head() -> str | None:
    """Return the current HEAD commit SHA (7 chars), or None if unavailable."""
    try:
        out = subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=Path(__file__).parent,
            stderr=subprocess.DEVNULL,
        )
        return out.decode().strip()
    except Exception:
        return None

try:
    import fcntl as _fcntl
    _HAS_FCNTL = True
except ImportError:
    _HAS_FCNTL = False

# Ensure vsevals package is importable when run directly from repo root
_here = Path(__file__).resolve().parent.parent
if str(_here) not in sys.path:
    sys.path.insert(0, str(_here))

from vsevals.loader import load_suite
from vsevals.models import RunConfig, RunResult
from vsevals.scorer import score_one

LOGGER = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Re-score completed matrix cells using a (new) judge model.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    p.add_argument("--matrix-dir", required=True, help="Path to the matrix output directory")
    p.add_argument("--suite", required=True, help="Path to suite YAML (e.g. suite.yaml)")

    # Judge model config
    p.add_argument("--judge-model", default=None,
                   help="Judge model override, e.g. openai:gpt-5 (default: from RunConfig / suite)")
    p.add_argument("--scoring-mode", default="llm",
                   choices=["llm", "hybrid"],
                   help="Scoring mode — LLM judge only (default: llm). 'hybrid' is an alias.")
    p.add_argument("--judge-format-variant", default="both",
                   choices=["verdict-true", "verdict-false", "none", "both", "pre-67f6ed0"],
                   help="Judge prompt format variant for ablation study: "
                        "'verdict-true' = single true example (anchors to true); "
                        "'verdict-false' = single false example (anchors to false); "
                        "'none' = abstract <bool> placeholder, no concrete example; "
                        "'both' = both true+false examples, corrected prompt (default); "
                        "'pre-67f6ed0' = exact old prompt before anchoring fix (single false example).")

    # Filters
    p.add_argument("--tasks",    default=None, help="Comma-separated task IDs to process (default: all)")
    p.add_argument("--variants", default=None, help="Comma-separated variant IDs to process (default: all)")
    p.add_argument("--models",   default=None, help="Comma-separated model names to process (default: all)")

    # Output naming
    p.add_argument("--output-suffix", default=None,
                   help="Suffix for output files: matrix_results__{suffix}.csv and "
                        "full_dump__{suffix}.json per run dir.  "
                        "Defaults to a slug derived from --judge-model.  "
                        "Pass '' (empty string) to overwrite originals (legacy behaviour).")

    # Behaviour
    p.add_argument("--force", action="store_true", default=False,
                   help="Re-score even rows that already have overall_score set")
    p.add_argument("--skip-error-rows", action="store_true", default=True,
                   help="Skip rows with status=error (default: True)")
    p.add_argument("--workers", type=int, default=4,
                   help="Number of parallel scoring workers (default: 4)")
    p.add_argument("--stagger-seconds", type=float, default=0.5,
                   help="Minimum seconds between consecutive judge API calls across all workers "
                        "(default: 0.5).  Use 0 to disable.")
    p.add_argument("--checkpoint-every", type=int, default=10,
                   help="Write the output CSV after every N completed rows (default: 10).  "
                        "Use 0 to disable checkpointing (write only at the end).")
    p.add_argument("--dry-run", action="store_true", default=False,
                   help="Print which rows would be processed without running anything")
    p.add_argument("--log-level", default="INFO", choices=["DEBUG", "INFO", "WARNING"])
    return p


# ---------------------------------------------------------------------------
# Scoring extraction helpers (mirrors run_matrix._result_to_row scoring block)
# ---------------------------------------------------------------------------


def _voltsnip_constraint_split(constraint_results: list[dict]) -> dict[str, Any]:
    """Split constraint results into VoltSnip-attributed vs generic."""
    vs_all     = [r for r in constraint_results if r.get("voltsnip_key")]
    gen_all    = [r for r in constraint_results if not r.get("voltsnip_key")]
    vs_passed  = [r for r in vs_all  if r.get("passed")]
    gen_passed = [r for r in gen_all if r.get("passed")]
    vs_total   = len(vs_all)
    gen_total  = len(gen_all)
    return {
        "voltsnip_constraints_total":     vs_total,
        "voltsnip_constraints_passed":    len(vs_passed),
        "voltsnip_constraint_pass_rate":  round(len(vs_passed) / vs_total, 4) if vs_total else None,
        "voltsnip_constraint_passed_ids": ";".join(r["id"] for r in vs_passed),
        "voltsnip_constraint_failed_ids": ";".join(r["id"] for r in vs_all if not r.get("passed")),
        "generic_constraints_total":      gen_total,
        "generic_constraints_passed":     len(gen_passed),
        "generic_constraint_pass_rate":   round(len(gen_passed) / gen_total, 4) if gen_total else None,
    }


def _compute_process_passed(run_result: RunResult) -> tuple[bool, str]:
    """Compute process compliance pass/fail independently of outcome correctness.

    Mirrors run_matrix._compute_process_passed — kept local so rescore_scoring.py
    remains a standalone script that doesn't import from another script.

    Returns (process_passed: bool, reason: str).
    reason is "" on pass; semicolon-joined failure tags on fail.
    """
    outcome_passed = bool(run_result.score and run_result.score.passed)
    if not outcome_passed:
        return False, "outcome_failed"

    failures: list[str] = []
    m = run_result.summary_metrics

    # Memory requirement: required snippets must have been retrieved
    if run_result.variant_memory_enabled and run_result.required_snippet_keys:
        required = set(run_result.required_snippet_keys)
        retrieved = {s.canonical_key or s.id for s in run_result.retrieved_snippets}
        missing = required - retrieved
        if missing:
            coverage = round(len(required & retrieved) / len(required), 3)
            failures.append(f"retrieval_incomplete(coverage={coverage})")

    # Tool requirement: must have called at least one tool, at least one success
    if run_result.variant_tools_enabled:
        if m.tool_call_count == 0:
            failures.append("no_tool_calls")
        elif m.tool_call_count == m.tool_error_count:
            failures.append(f"all_tool_calls_failed({m.tool_error_count} errors)")

    if failures:
        return False, ";".join(failures)
    return True, ""


def _score_fields_from_result(
    score,
    scoring_latency_ms: int | None = None,
    cfg: RunConfig | None = None,
) -> dict[str, Any]:
    """Extract all scoring CSV columns from a ScoreResult object.

    scoring_judge_model / scoring_mode / judge_model_count / judge_ensemble_used are NOT
    attributes of ScoreResult — they live on RunConfig and are populated here from cfg.
    """
    s = score
    passed_constraint_ids = ";".join(r["id"] for r in s.constraint_results if r.get("passed"))
    failed_constraint_ids = ";".join(r["id"] for r in s.constraint_results if not r.get("passed"))
    llm_verdict_ids = ";".join(
        r["id"] for r in s.constraint_results if r.get("llm_verdict")
    )
    _keep = {"id", "passed", "llm_verdict", "expected", "voltsnip_key"}
    constraint_results_json = json.dumps(
        [{k: v for k, v in r.items() if k in _keep} for r in s.constraint_results],
        separators=(",", ":"),
    )
    llm_verdict_count = sum(1 for r in s.constraint_results if r.get("llm_verdict") is not None)
    vs = _voltsnip_constraint_split(s.constraint_results)

    # Derive judge metadata from cfg (not ScoreResult)
    judge_model_str = cfg.scoring_judge_model if cfg else None
    scoring_mode_str = (cfg.scoring_match_mode or "llm") if cfg else None
    judge_specs = [p.strip() for p in judge_model_str.split("+") if p.strip()] if judge_model_str else []
    judge_model_count = len(judge_specs)
    judge_ensemble_used = judge_model_count > 1

    fields: dict[str, Any] = {
        "overall_score":               s.overall_score,
        "passed":                      s.passed,
        "scoring_judge_model":         judge_model_str,
        "scoring_mode":                scoring_mode_str,
        "judge_model_count":           judge_model_count or None,
        "judge_ensemble_used":         judge_ensemble_used,
        "constraint_scoring_used":     s.constraint_scoring_used,
        "constraint_checks_passed":    s.constraint_checks_passed,
        "constraint_checks_total":     s.constraint_checks_total,
        "constraint_failed_count": (
            (s.constraint_checks_total - s.constraint_checks_passed)
            if s.constraint_checks_total is not None and s.constraint_checks_passed is not None
            else None
        ),
        "constraint_pass_rate": (
            round(s.constraint_checks_passed / s.constraint_checks_total, 4)
            if s.constraint_checks_total and s.constraint_checks_passed is not None
            else None
        ),
        "constraint_pass_threshold":    s.constraint_pass_threshold,
        "constraint_passed_ids":        passed_constraint_ids,
        "constraint_failed_ids":        failed_constraint_ids,
        "constraint_llm_verdict_ids":   llm_verdict_ids,
        "constraint_results_json":      constraint_results_json,
        "constraint_llm_verdict_count": llm_verdict_count,
        **vs,
        "hidden_requirements_score":    s.hidden_requirements.score,
        "hidden_requirements_matched":  s.hidden_requirements.matched,
        "hidden_requirements_total":    s.hidden_requirements.total,
        "success_indicators_score":     s.success_indicators.score,
        "success_indicators_matched":   s.success_indicators.matched,
        "success_indicators_total":     s.success_indicators.total,
        "failure_modes_score":          s.failure_modes.score,
        "failure_modes_matched":        s.failure_modes.matched,
        "failure_modes_total":          s.failure_modes.total,
        "evaluation_criteria_score":    s.evaluation_criteria.score,
        "evaluation_criteria_matched":  s.evaluation_criteria.matched,
        "evaluation_criteria_total":    s.evaluation_criteria.total,
        "evaluation_criteria_notes":    ";".join(s.evaluation_criteria_notes),
    }
    if scoring_latency_ms is not None:
        fields["scoring_latency_ms"] = scoring_latency_ms
    return fields


# ---------------------------------------------------------------------------
# Output-file naming helpers
# ---------------------------------------------------------------------------


def _make_rate_limiter(stagger_seconds: float):
    """Return a thread-safe callable that enforces a minimum gap between API calls.

    All parallel workers share the same rate-limiter instance so the stagger
    applies globally (not per-worker).  Returns None when stagger_seconds <= 0.
    """
    import threading as _threading

    if stagger_seconds <= 0:
        return None

    _lock = _threading.Lock()
    _state = {"last_call": 0.0}

    def _wait():
        with _lock:
            now = time.monotonic()
            wait = _state["last_call"] + stagger_seconds - now
            if wait > 0:
                time.sleep(wait)
            _state["last_call"] = time.monotonic()

    return _wait


def _model_slug(judge_model: str) -> str:
    """Derive a filesystem-safe slug from a judge model string.

    Examples:
        "openai:gpt-5.2"                             → "gpt-5.2"
        "anthropic:claude-opus-4-6"                  → "claude-opus-4-6"
        "openai:gpt-5.2+anthropic:claude-opus-4-6"  → "gpt-5.2+claude-opus-4-6"
    """
    import re
    parts = judge_model.split("+")
    slugs = []
    for p in parts:
        # Strip provider prefix (everything up to and including the first colon)
        model_part = p.split(":", 1)[-1].strip()
        # Replace characters unsafe in filenames with "-"
        model_part = re.sub(r"[^\w.\-+]", "-", model_part)
        slugs.append(model_part)
    return "+".join(slugs)


# ---------------------------------------------------------------------------
# Core per-row logic
# ---------------------------------------------------------------------------


def _rescore_row(
    row: dict,
    suite,
    cfg: RunConfig,
    provider_keys: dict[str, str],
    dump_suffix: str | None = None,
    rate_limit_fn=None,
) -> tuple[dict, str | None]:
    """Re-score one matrix row.  Returns (updated_row, error_msg|None).

    dump_suffix:    if set (non-empty), write full_dump__{dump_suffix}.json instead of
                    overwriting the original full_dump.json.  Pass None/"" to overwrite.
    rate_limit_fn:  optional callable() that blocks until the next API call is allowed
                    (shared across all workers for global stagger enforcement).
    """
    task_id   = row.get("task_id", "")
    run_dir   = row.get("run_dir", "")
    full_dump = row.get("full_dump_json", "")

    # Validate paths
    if not run_dir or not Path(run_dir).exists():
        return row, f"run_dir not found: {run_dir!r}"

    # Locate full_dump.json
    dump_path = Path(full_dump) if full_dump and Path(full_dump).exists() else None
    if dump_path is None:
        # Fallback: look in run_dir
        fallback = Path(run_dir) / "full_dump.json"
        if fallback.exists():
            dump_path = fallback
    if dump_path is None:
        return row, f"full_dump.json not found for run_dir={run_dir!r}"

    # Deserialise RunResult
    try:
        raw_json = dump_path.read_text(encoding="utf-8")
        run_result = RunResult.model_validate(json.loads(raw_json))
    except Exception as exc:
        return row, f"failed to load full_dump.json: {exc}"

    # Load task oracle
    task = suite.task_map.get(task_id)
    if not task:
        return row, f"task {task_id!r} not found in suite"

    # Enforce global stagger before hitting the judge API
    if rate_limit_fn is not None:
        rate_limit_fn()

    # Run score_one
    t0 = time.perf_counter()
    try:
        score = score_one(
            run_result=run_result,
            oracle=task.oracle,
            cfg=cfg,
            provider_keys=provider_keys,
        )
    except Exception as exc:
        LOGGER.exception("score_one raised for task=%s", task_id)
        return row, f"score_one failed: {exc}"
    scoring_latency_ms = int((time.perf_counter() - t0) * 1000)

    # Update row with new score fields
    row.update(_score_fields_from_result(score, scoring_latency_ms=scoring_latency_ms, cfg=cfg))

    # Recompute process compliance now that outcome score is fresh
    run_result.score = score   # set first so _compute_process_passed sees updated outcome
    process_passed, process_fail_reason = _compute_process_passed(run_result)
    row.update({
        "process_passed":      process_passed,
        "process_fail_reason": process_fail_reason,
        "full_pass":           bool(score.passed and process_passed),
    })

    # Write the scored full_dump to disk.
    # If dump_suffix is set, write to full_dump__{suffix}.json to preserve the original.
    if dump_suffix:
        out_dump_path = Path(run_dir) / f"full_dump__{dump_suffix}.json"
    else:
        out_dump_path = dump_path
    try:
        dump_dict = run_result.model_dump(mode="json")
        # Inject rescore provenance so every artifact is self-documenting.
        dump_dict["rescore_provenance"] = {
            "scorer_commit":        _git_head(),
            "judge_prompt_variant": getattr(cfg, "judge_prompt_variant", "both"),
            "judge_model":          getattr(cfg, "scoring_judge_model", None),
            "output_suffix":        dump_suffix or None,
            "rescore_timestamp":    time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }
        out_dump_path.write_text(
            json.dumps(dump_dict, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
    except Exception as exc:
        LOGGER.warning("could not write %s for %s: %s", out_dump_path.name, run_dir, exc)

    status = "PASS" if score.passed else "FAIL"
    LOGGER.info(
        "  → %s  score=%.3f  latency=%dms  [%s/%s/%s]",
        status, score.overall_score, scoring_latency_ms,
        task_id, row.get("variant_id"), row.get("model_name"),
    )
    return row, None


# ---------------------------------------------------------------------------
# CSV write-back (identical to rescore_pytest._write_csv)
# ---------------------------------------------------------------------------


def _write_csv(csv_path: Path, rows: list[dict]) -> None:
    """Write all rows back to the CSV, preserving all columns (union of all keys)."""
    if not rows:
        return
    all_keys: list[str] = []
    seen: set[str] = set()
    for row in rows:
        for k in row:
            if k not in seen:
                all_keys.append(k)
                seen.add(k)

    with csv_path.open("w", newline="", encoding="utf-8") as f:
        if _HAS_FCNTL:
            _fcntl.flock(f, _fcntl.LOCK_EX)
        writer = csv.DictWriter(f, fieldnames=all_keys, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow(row)
        if _HAS_FCNTL:
            _fcntl.flock(f, _fcntl.LOCK_UN)
    LOGGER.info("wrote %d rows → %s", len(rows), csv_path)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        datefmt="%H:%M:%S",
    )

    # Early API key check: fail fast if the judge model's provider has no key.
    if args.judge_model:
        judge_model = args.judge_model
        needs_openai = "openai" in judge_model.lower()
        needs_anthropic = "anthropic" in judge_model.lower()
        if needs_openai and not os.environ.get("OPENAI_API_KEY"):
            print("ERROR: OPENAI_API_KEY not set but judge model requires OpenAI.", file=sys.stderr)
            sys.exit(1)
        if needs_anthropic and not os.environ.get("ANTHROPIC_API_KEY"):
            print("ERROR: ANTHROPIC_API_KEY not set but judge model requires Anthropic.", file=sys.stderr)
            sys.exit(1)

    matrix_dir = Path(args.matrix_dir)

    # Compute output suffix for separate-file mode.
    # --output-suffix "" means overwrite originals (legacy); omitting it auto-derives from judge.
    if args.output_suffix is not None:
        output_suffix = args.output_suffix  # may be "" → overwrite mode
    elif args.judge_model:
        output_suffix = _model_slug(args.judge_model)
    else:
        output_suffix = ""  # no judge override → overwrite mode

    # Input CSV is always the canonical matrix_results.csv
    csv_path = matrix_dir / "matrix_results.csv"
    if not csv_path.exists():
        parser.error(f"matrix CSV not found: {csv_path}")

    # Output CSV uses suffix when set
    out_csv_path = (
        matrix_dir / f"matrix_results__{output_suffix}.csv"
        if output_suffix
        else csv_path
    )
    if output_suffix:
        LOGGER.info("output CSV → %s", out_csv_path.name)

    # Build rate limiter (shared across all workers)
    rate_limit_fn = _make_rate_limiter(args.stagger_seconds)
    if rate_limit_fn:
        LOGGER.info(
            "rate limiter: stagger=%.2fs  workers=%d  → max ~%d calls/min",
            args.stagger_seconds, args.workers,
            int(60 / args.stagger_seconds),
        )

    suite = load_suite(args.suite)

    # Build RunConfig from CLI args
    cfg_kwargs: dict[str, Any] = {}
    if args.judge_model:
        cfg_kwargs["scoring_judge_model"] = args.judge_model
    if args.scoring_mode:
        cfg_kwargs["scoring_match_mode"] = args.scoring_mode
    if args.judge_format_variant:
        cfg_kwargs["judge_prompt_variant"] = args.judge_format_variant
    cfg = RunConfig(**cfg_kwargs)

    # Load provider keys from environment (mirrors runner._load_provider_keys)
    provider_keys: dict[str, str] = {}
    for provider, env_key in (("openai", "OPENAI_API_KEY"), ("anthropic", "ANTHROPIC_API_KEY")):
        val = os.environ.get(env_key)
        if val:
            provider_keys[provider] = val
    # Also try loading from .env if present (mirrors _load_dotenv_keys)
    try:
        from vsevals.runner import _load_dotenv_keys
        provider_keys.update(_load_dotenv_keys())
    except Exception:
        pass

    # Load CSV
    with csv_path.open(encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    LOGGER.info("loaded %d rows from %s", len(rows), csv_path)

    # Parse filters
    filter_tasks    = {t.strip() for t in args.tasks.split(",")    if t.strip()} if args.tasks    else None
    filter_variants = {v.strip() for v in args.variants.split(",") if v.strip()} if args.variants else None
    filter_models   = {m.strip() for m in args.models.split(",")   if m.strip()} if args.models   else None

    # Identify rows to process
    to_process: list[int] = []
    for i, row in enumerate(rows):
        if filter_tasks    and row.get("task_id")    not in filter_tasks:
            continue
        if filter_variants and row.get("variant_id") not in filter_variants:
            continue
        if filter_models   and row.get("model_name") not in filter_models:
            continue
        if args.skip_error_rows and row.get("status") == "error":
            continue
        # Skip rows that already have a score unless --force
        if not args.force:
            score_val = row.get("overall_score", "").strip()
            if score_val and score_val not in ("", "None"):
                continue
        # Must have a run_dir to locate full_dump.json
        if not row.get("run_dir"):
            continue
        to_process.append(i)

    LOGGER.info(
        "%d/%d rows need scoring  (force=%s  filters: tasks=%s variants=%s models=%s)",
        len(to_process), len(rows), args.force,
        filter_tasks, filter_variants, filter_models,
    )

    if not to_process:
        LOGGER.info("nothing to do")
        return

    if args.dry_run:
        print(f"\nDry-run: would rescore {len(to_process)} rows:")
        for i in to_process:
            r = rows[i]
            print(f"  [{i+1}/{len(rows)}]  {r.get('task_id')}/{r.get('variant_id')}/{r.get('model_name')}"
                  f"  full_dump={r.get('full_dump_json', 'N/A')!r}")
        return

    # Run scoring for each row (sequential or parallel)
    import queue as _queue
    import threading

    errors: list[str] = []
    checkpoint_every = args.checkpoint_every

    def _maybe_checkpoint(completed: int) -> None:
        """Write CSV if this completion count hits the checkpoint interval."""
        if checkpoint_every > 0 and completed % checkpoint_every == 0:
            LOGGER.info("checkpoint: writing %d rows → %s", len(rows), out_csv_path.name)
            _write_csv(out_csv_path, rows)

    if args.workers <= 1:
        for idx, i in enumerate(to_process, 1):
            row = rows[i]
            LOGGER.info(
                "[%d/%d] task=%s variant=%s model=%s",
                idx, len(to_process),
                row.get("task_id"), row.get("variant_id"), row.get("model_name"),
            )
            rows[i], err = _rescore_row(row, suite, cfg, provider_keys,
                                         dump_suffix=output_suffix, rate_limit_fn=rate_limit_fn)
            if err:
                errors.append(f"{row.get('task_id')}/{row.get('variant_id')}: {err}")
                LOGGER.error("  ✗ %s", err)
            _maybe_checkpoint(idx)
    else:
        results_lock = threading.Lock()
        task_queue: _queue.Queue = _queue.Queue()
        for i in to_process:
            task_queue.put(i)
        started_count = [0]
        completed_count = [0]

        def _worker() -> None:
            while True:
                try:
                    i = task_queue.get(timeout=2)
                except _queue.Empty:
                    return
                try:
                    with results_lock:
                        started_count[0] += 1
                        n = started_count[0]
                    row = rows[i]
                    LOGGER.info(
                        "[%d/%d] task=%s variant=%s model=%s",
                        n, len(to_process),
                        row.get("task_id"), row.get("variant_id"), row.get("model_name"),
                    )
                    updated, err = _rescore_row(row, suite, cfg, provider_keys,
                                                dump_suffix=output_suffix, rate_limit_fn=rate_limit_fn)
                    with results_lock:
                        rows[i] = updated
                        if err:
                            errors.append(f"{row.get('task_id')}/{row.get('variant_id')}: {err}")
                            LOGGER.error("  ✗ %s", err)
                        completed_count[0] += 1
                        _maybe_checkpoint(completed_count[0])
                except Exception as exc:
                    LOGGER.error("unhandled worker exception: %s", exc)
                finally:
                    task_queue.task_done()

        threads = [
            threading.Thread(target=_worker, daemon=True, name=f"scorer-{i}")
            for i in range(args.workers)
        ]
        for t in threads:
            t.start()
        task_queue.join()
        for t in threads:
            t.join(timeout=5.0)

    # Final write (captures any rows after the last checkpoint)
    _write_csv(out_csv_path, rows)

    # Summary
    processed = len(to_process)
    err_count = len(errors)
    ok_count  = processed - err_count
    LOGGER.info(
        "done  processed=%d  ok=%d  errors=%d",
        processed, ok_count, err_count,
    )
    if errors:
        LOGGER.warning("%d errors:", len(errors))
        for e in errors:
            LOGGER.warning("  • %s", e)
        sys.exit(1)


if __name__ == "__main__":
    main()
