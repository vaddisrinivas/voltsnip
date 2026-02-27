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

  # Pass 2 — re-score with a better ensemble judge
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
import sys
import time
from pathlib import Path
from typing import Any

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

    # Filters
    p.add_argument("--tasks",    default=None, help="Comma-separated task IDs to process (default: all)")
    p.add_argument("--variants", default=None, help="Comma-separated variant IDs to process (default: all)")
    p.add_argument("--models",   default=None, help="Comma-separated model names to process (default: all)")

    # Behaviour
    p.add_argument("--force", action="store_true", default=False,
                   help="Re-score even rows that already have overall_score set")
    p.add_argument("--skip-error-rows", action="store_true", default=True,
                   help="Skip rows with status=error (default: True)")
    p.add_argument("--workers", type=int, default=1,
                   help="Number of parallel scoring workers (default: 1 = sequential)")
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


def _score_fields_from_result(score, scoring_latency_ms: int | None = None) -> dict[str, Any]:
    """Extract all scoring CSV columns from a ScoreResult object."""
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

    fields: dict[str, Any] = {
        "overall_score":               s.overall_score,
        "passed":                      s.passed,
        "scoring_judge_model":         s.scoring_judge_model,
        "scoring_mode":                s.scoring_mode,
        "judge_model_count":           s.judge_model_count,
        "judge_ensemble_used":         s.judge_ensemble_used,
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
# Core per-row logic
# ---------------------------------------------------------------------------


def _rescore_row(
    row: dict,
    suite,
    cfg: RunConfig,
    provider_keys: dict[str, str],
) -> tuple[dict, str | None]:
    """Re-score one matrix row.  Returns (updated_row, error_msg|None)."""
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
    row.update(_score_fields_from_result(score, scoring_latency_ms=scoring_latency_ms))

    # Recompute process compliance now that outcome score is fresh
    run_result.score = score   # set first so _compute_process_passed sees updated outcome
    process_passed, process_fail_reason = _compute_process_passed(run_result)
    row.update({
        "process_passed":      process_passed,
        "process_fail_reason": process_fail_reason,
        "full_pass":           bool(score.passed and process_passed),
    })

    # Also write the updated full_dump.json so the on-disk artifact stays in sync
    try:
        dump_path.write_text(
            json.dumps(run_result.model_dump(mode="json"), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
    except Exception as exc:
        LOGGER.warning("could not update full_dump.json for %s: %s", run_dir, exc)

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

    matrix_dir = Path(args.matrix_dir)
    csv_path = matrix_dir / "matrix_results.csv"
    if not csv_path.exists():
        parser.error(f"matrix CSV not found: {csv_path}")

    suite = load_suite(args.suite)

    # Build RunConfig from CLI args
    cfg_kwargs: dict[str, Any] = {}
    if args.judge_model:
        cfg_kwargs["scoring_judge_model"] = args.judge_model
    if args.scoring_mode:
        cfg_kwargs["scoring_match_mode"] = args.scoring_mode
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

    if args.workers <= 1:
        for idx, i in enumerate(to_process, 1):
            row = rows[i]
            LOGGER.info(
                "[%d/%d] task=%s variant=%s model=%s",
                idx, len(to_process),
                row.get("task_id"), row.get("variant_id"), row.get("model_name"),
            )
            rows[i], err = _rescore_row(row, suite, cfg, provider_keys)
            if err:
                errors.append(f"{row.get('task_id')}/{row.get('variant_id')}: {err}")
                LOGGER.error("  ✗ %s", err)
    else:
        results_lock = threading.Lock()
        task_queue: _queue.Queue = _queue.Queue()
        for i in to_process:
            task_queue.put(i)
        started_count = [0]

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
                    updated, err = _rescore_row(row, suite, cfg, provider_keys)
                    with results_lock:
                        rows[i] = updated
                        if err:
                            errors.append(f"{row.get('task_id')}/{row.get('variant_id')}: {err}")
                            LOGGER.error("  ✗ %s", err)
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

    # Write results back
    _write_csv(csv_path, rows)

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
