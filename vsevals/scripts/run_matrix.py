#!/usr/bin/env python3
"""Matrix runner: run all (task x variant x model) combinations."""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import subprocess
import sys
import queue as _queue
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, NamedTuple

# Ensure vsevals package is importable
_here = Path(__file__).resolve().parent.parent
if str(_here) not in sys.path:
    sys.path.insert(0, str(_here))

from vsevals.loader import load_suite
from vsevals.models import RunConfig, RunResult
from vsevals.runner import run_one
from vsevals.exporters.concurrency import ProviderThrottle
from vsevals.exporters.csv_mapper import (
    result_to_row, append_completed_entry, load_completed, row_from_dump, error_row,
    CANONICAL_COLUMNS,
)
from vsevals.exporters.scoreboard import print_scoreboard
from vsevals.exporters.report_writer import write_summary

LOGGER = logging.getLogger(__name__)

class Cell(NamedTuple):
    task_id: str
    variant_id: str
    model_name: str

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Run a matrix of (task x variant x model) evaluations.")
    p.add_argument("--suite", required=True)
    p.add_argument("--models", default=None)
    p.add_argument("--variants", default=None)
    p.add_argument("--priority-variants", default=None)
    p.add_argument("--tasks", default=None)
    p.add_argument("--output-dir", default="./vsevals_runs")
    p.add_argument("--matrix-dir", default=None)
    p.add_argument("--judge-model", default="openai:gpt-5.2+anthropic:claude-opus-4-6")
    p.add_argument("--scoring-mode", default="llm", choices=["llm", "hybrid"])
    p.add_argument("--constraint-threshold", type=float, default=0.7)
    p.add_argument("--repo-root", default=None)
    p.add_argument("--voltsnip-url", default=None)
    p.add_argument("--spacing", type=float, default=0.35)
    p.add_argument("--log-level", default="INFO", choices=["DEBUG", "INFO", "WARNING"])
    p.add_argument("--no-scoring", action="store_true", default=False)
    p.add_argument("--no-pytest", action="store_true", default=False)
    p.add_argument("--pytest-docker-image", default=None)
    p.add_argument("--pytest-timeout", type=int, default=300)
    p.add_argument("--max-tokens", type=int, default=None)
    p.add_argument("--llm-timeout", type=int, default=300)
    p.add_argument("--max-tool-roundtrips", type=int, default=None)
    p.add_argument("--workers", type=int, default=1)
    p.add_argument("--provider-concurrency", type=int, default=3)
    p.add_argument("--resume", default=None)
    p.add_argument("--instruction-mode", default=None, choices=["none", "explicit"],
                   help="Override instruction_mode on ALL variants (use 'explicit' to run the full explicit-instruction pass).")
    p.add_argument("--reasoning-effort", default=None, choices=["low", "medium", "high"],
                   help="Reasoning effort for reasoning-capable models. openai: maps to reasoning_effort API param. codex: maps to -c model_reasoning_effort. Ignored by claude/anthropic providers.")
    p.add_argument("--debugpy", action="store_true", default=False, help="Wait for a debugpy client before starting.")
    p.add_argument("--debugpy-port", type=int, default=5678, metavar="PORT", help="Port for debugpy to listen on (default: 5678).")
    return p

def main() -> None:
    args = build_parser().parse_args()

    if args.debugpy:
        import debugpy  # pip install debugpy
        debugpy.listen(("0.0.0.0", args.debugpy_port))
        print(f"⏳  debugpy listening on port {args.debugpy_port} — attach your debugger now…", flush=True)
        debugpy.wait_for_client()
        print("✅  debugpy client attached, continuing.", flush=True)

    logging.basicConfig(level=getattr(logging, args.log_level), format="%(asctime)s %(levelname)s %(name)s %(message)s", datefmt="%H:%M:%S")

    suite = load_suite(args.suite)
    models = [m.strip() for m in args.models.split(",") if m.strip()] if args.models else suite.model_names
    variants = [v.strip() for v in args.variants.split(",")] if args.variants else list(suite.variant_map)
    if args.priority_variants:
        priority = [v.strip() for v in args.priority_variants.split(",") if v.strip()]
        variants = [v for v in priority if v in set(variants)] + [v for v in variants if v not in set(priority)]
    tasks = [t.strip() for t in args.tasks.split(",")] if args.tasks else list(suite.task_map)
    
    suite_sha256 = _sha256_file(Path(args.suite))
    git_meta = _git_metadata(Path(args.suite).expanduser().resolve().parent)
    judge_specs = [m.strip() for m in args.judge_model.split("+") if m.strip()]

    # Apply CLI overrides to suite variants BEFORE computing spec hashes so that
    # recorded hashes reflect the actual run config, not the raw YAML values.
    if args.max_tool_roundtrips is not None:
        for variant in suite.variants:
            if variant.tools_enabled: variant.max_tool_roundtrips = args.max_tool_roundtrips

    if args.instruction_mode is not None:
        for variant in suite.variants:
            variant.instruction_mode = args.instruction_mode

    # Hashes computed post-override → provenance is accurate even when CLI flags mutate variants.
    task_spec_hashes = _task_spec_hashes(suite)
    variant_spec_hashes = _variant_spec_hashes(suite)

    cfg_kwargs = dict(
        voltsnip_base_url=args.voltsnip_url,
        scoring_judge_model=args.judge_model,
        scoring_match_mode=args.scoring_mode,
        constraint_pass_threshold=args.constraint_threshold,
        skip_scoring=args.no_scoring,
        auto_apply_patch=not args.no_pytest,
        pytest_timeout_seconds=args.pytest_timeout,
        llm_timeout_seconds=args.llm_timeout,
        max_tokens=args.max_tokens,
    )
    if args.pytest_docker_image:
        cfg_kwargs["pytest_docker_image"] = args.pytest_docker_image
    if args.reasoning_effort:
        cfg_kwargs["reasoning_effort"] = args.reasoning_effort
        
    cfg = RunConfig(**cfg_kwargs)

    all_cells = [Cell(t, v, m) for t in tasks for v in variants for m in models]
    matrix_dir = Path(args.resume) if args.resume else (Path(args.matrix_dir) if args.matrix_dir else Path(args.output_dir) / f"matrix_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')}")
    matrix_dir.mkdir(parents=True, exist_ok=True)

    completed = load_completed(matrix_dir)
    cells_to_run = [c for c in all_cells if f"{c.task_id}/{c.variant_id}/{c.model_name}" not in completed]
    LOGGER.info("matrix plan: %d cells (%d tasks x %d variants x %d models)", len(all_cells), len(tasks), len(variants), len(models))
    if completed: LOGGER.info("skipping %d completed cells, running %d remaining", len(all_cells) - len(cells_to_run), len(cells_to_run))

    row_meta = dict(
        scoring_judge_model=args.judge_model, scoring_mode=args.scoring_mode,
        judge_model_count=len(judge_specs), judge_ensemble_used=len(judge_specs) > 1,
        git_commit=git_meta.get("git_commit"), git_branch=git_meta.get("git_branch"),
        git_dirty=git_meta.get("git_dirty"), suite_sha256=suite_sha256,
    )

    # On resume: rebuild live results from full_dump.json artifacts so the
    # scoreboard and final report reflect previously completed cells.
    results: list[dict] = []
    for key, entry in completed.items():
        run_dir = entry.get("run_dir", "")
        dump_path = Path(run_dir) / "full_dump.json" if run_dir else None
        if dump_path and dump_path.exists():
            try:
                row = row_from_dump(dump_path)
                row.update(row_meta)
                row["task_spec_hash"] = entry.get("task_spec_hash")
                row["variant_spec_hash"] = entry.get("variant_spec_hash")
                results.append(row)
                continue
            except Exception as exc:
                LOGGER.warning("could not rebuild row for %s: %s", key, exc)
        # Fall back: minimal entry so the cell is still counted as completed
        results.append({
            "task_id": entry.get("task_id", ""),
            "variant_id": entry.get("variant_id", ""),
            "model_name": entry.get("model_name", ""),
            "status": entry.get("status", "error"),
        })
    results_lock = threading.Lock()
    done_count = [len(completed)]
    started_count = [0]
    scoreboard_interval = max(1, len(all_cells) // 20)

    # Note: ProviderThrottle now supports per-provider limits efficiently
    throttle = ProviderThrottle({m.split(":")[0].lower(): args.provider_concurrency for m in models}, stagger_ms=int(args.spacing * 1000))

    def _run_cell(cell: Cell) -> dict:
        provider = cell.model_name.split(":")[0].lower()
        throttle.acquire(provider)
        try:
            with results_lock:
                started_count[0] += 1
                n = started_count[0]
            LOGGER.info("[%d/%d] task=%s variant=%s model=%s", n, len(cells_to_run), cell.task_id, cell.variant_id, cell.model_name)
            try:
                res = run_one(task_id=cell.task_id, variant_id=cell.variant_id, model_name=cell.model_name, suite_path=args.suite, output_dir=str(matrix_dir / "runs"), repo_root=args.repo_root, cfg=cfg)
                row = result_to_row(res)
            except Exception as exc:
                LOGGER.error("cell failed %s: %s", cell, exc)
                row = error_row(cell.task_id, cell.variant_id, cell.model_name, exc)

            row.update(row_meta)
            row["task_spec_hash"] = task_spec_hashes.get(cell.task_id)
            row["variant_spec_hash"] = variant_spec_hashes.get(cell.variant_id)

            # Write lightweight tracking entry — CSV is built separately by build_matrix_csv.py
            run_dir = row.get("run_dir", "")
            append_completed_entry(matrix_dir / "completed.jsonl", {
                "task_id": cell.task_id,
                "variant_id": cell.variant_id,
                "model_name": cell.model_name,
                "run_dir": run_dir,
                "status": row.get("status", "error"),
                "finished_at": datetime.now(timezone.utc).isoformat(),
                "task_spec_hash": task_spec_hashes.get(cell.task_id),
                "variant_spec_hash": variant_spec_hashes.get(cell.variant_id),
            })
            with results_lock:
                results.append(row)
                done_count[0] += 1
                if done_count[0] % scoreboard_interval == 0:
                    print_scoreboard(results, len(all_cells))
            return row
        finally:
            throttle.release(provider)

    if args.workers == 1:
        for c in cells_to_run: _run_cell(c)
    else:
        q: _queue.Queue = _queue.Queue()
        for c in cells_to_run: q.put(c)
        def _worker():
            while True:
                c = q.get()
                if c is None: q.task_done(); break
                try: _run_cell(c)
                except Exception as e: LOGGER.error("worker error: %s", e)
                finally: q.task_done()
        ts = [threading.Thread(target=_worker, daemon=True) for _ in range(args.workers)]
        for t in ts: t.start()
        q.join()
        for _ in ts: q.put(None)
        for t in ts: t.join(timeout=5.0)

    write_summary(matrix_dir, results, args.suite, args.models or "", args.variants or "", args.tasks or "", args.judge_model)
    print_scoreboard(results, len(all_cells))

    # Build CSV from the in-memory results list (ok + error — no survivorship bias).
    # Previously this re-loaded from completed.jsonl with a status==ok filter, which
    # silently dropped every error cell from the CSV.  Using `results` directly
    # preserves all cells and avoids a redundant disk round-trip.
    _csv_path = matrix_dir / "matrix_results.csv"
    try:
        import csv as _csv
        _csv_rows: list[dict] = list(results)
        _all_keys = list(CANONICAL_COLUMNS) + sorted({k for r in _csv_rows for k in r if k not in set(CANONICAL_COLUMNS)})
        with _csv_path.open("w", newline="", encoding="utf-8") as _f:
            _w = _csv.DictWriter(_f, fieldnames=_all_keys, extrasaction="ignore")
            _w.writeheader()
            for _row in _csv_rows:
                _w.writerow({k: _row.get(k, "") for k in _all_keys})
        LOGGER.info("CSV written: %s (%d rows, %d ok / %d error)", _csv_path, len(_csv_rows),
                    sum(1 for r in _csv_rows if r.get("status") == "ok"),
                    sum(1 for r in _csv_rows if r.get("status") != "ok"))
    except Exception as _exc:
        LOGGER.warning("CSV build failed: %s — run build_matrix_csv.py manually", _exc)

    print(f"  CSV:    {_csv_path}")
    print(f"  Report: {matrix_dir}/matrix_report.md")

def _sha256_file(path: Path) -> str | None:
    try: return hashlib.sha256(path.read_bytes()).hexdigest()
    except: return None

def _json_sha256(payload: dict) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()

def _task_spec_hashes(suite: Any) -> dict[str, str]:
    return {t.id: _json_sha256(t.model_dump(mode="json")) for t in suite.tasks}

def _variant_spec_hashes(suite: Any) -> dict[str, str]:
    return {v.id: _json_sha256(v.model_dump(mode="json")) for v in suite.variants}

def _git_metadata(cwd: Path) -> dict[str, Any]:
    def _run(args):
        try: return subprocess.run(["git", *args], cwd=str(cwd), capture_output=True, text=True).stdout.strip()
        except: return None
    root = _run(["rev-parse", "--show-toplevel"])
    if not root: return {}
    return {"git_commit": _run(["rev-parse", "HEAD"]), "git_branch": _run(["rev-parse", "--abbrev-ref", "HEAD"]), "git_dirty": bool(_run(["status", "--porcelain"]))}

if __name__ == "__main__":
    main()
