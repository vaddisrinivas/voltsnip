#!/usr/bin/env python3
"""Post-hoc pytest runner: run Docker pytest on already-completed matrix cells.

Reads matrix_results.csv, finds rows where pytest hasn't run yet
(pytest_ran is empty/false), applies the generated code patch, runs pytest
in Docker, and writes updated results back to the CSV.

Rows are updated *in-place* — existing fields are preserved, pytest fields
are filled in or overwritten.  Error rows (status=error, empty code_output)
are automatically skipped.

Usage
-----
    # Run pytest on all cells in a matrix that haven't been tested yet
    python scripts/rescore_pytest.py \\
        --matrix-dir ./vsevals_runs/matrix_20260226T120000Z \\
        --suite suite.yaml

    # Limit to specific tasks / variants / models
    python scripts/rescore_pytest.py \\
        --matrix-dir ./vsevals_runs/matrix_20260226T120000Z \\
        --suite suite.yaml \\
        --tasks BUG01,BUG02 --variants P6a,P6b

    # Override repo root and Docker image
    python scripts/rescore_pytest.py \\
        --matrix-dir ./vsevals_runs/matrix_20260226T120000Z \\
        --suite suite.yaml \\
        --repo-root /path/to/repo \\
        --pytest-docker-image moltsnip-hybrid-pytest:latest

    # Dry-run: show which rows would be processed without running anything
    python scripts/rescore_pytest.py \\
        --matrix-dir ./vsevals_runs/matrix_20260226T120000Z \\
        --suite suite.yaml --dry-run
"""

from __future__ import annotations

import argparse
import csv
import logging
import re
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
from vsevals.models import PytestResult, RunConfig
from vsevals.patching import apply_line_range_rewrite
from vsevals.pytest_runner import docker_cp, run_pytest_in_docker, start_test_container, stop_test_container
from vsevals.runner import _container_file_path

LOGGER = logging.getLogger(__name__)

_PYTEST_SUMMARY_ITEM_RE = re.compile(
    r"(?P<count>\d+)\s+(?P<label>passed|failed|skipped|xfailed|xpassed|error|errors|deselected)\b",
    flags=re.IGNORECASE,
)
_PYTEST_COLLECTED_RE = re.compile(r"\bcollected\s+(?P<count>\d+)\s+items?\b", flags=re.IGNORECASE)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Run pytest post-hoc on already-completed matrix cells.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    p.add_argument("--matrix-dir", required=True, help="Path to the matrix output directory")
    p.add_argument("--suite", required=True, help="Path to suite YAML (e.g. suite.yaml)")

    # Filters
    p.add_argument("--tasks", default=None, help="Comma-separated task IDs to process (default: all)")
    p.add_argument("--variants", default=None, help="Comma-separated variant IDs to process (default: all)")
    p.add_argument("--models", default=None, help="Comma-separated model names to process (default: all)")

    # Pytest config
    p.add_argument("--repo-root", default=None,
                   help="Override repo root for all tasks (default: from task YAML)")
    p.add_argument("--pytest-docker-image", default=None,
                   help="Docker image for pytest (default: from usecase.yaml or moltsnip-pytest:latest)")
    p.add_argument("--pytest-docker-workdir", default=None,
                   help="Docker workdir for pytest (default: from usecase.yaml or /workspace)")
    p.add_argument("--pytest-timeout", type=int, default=300,
                   help="pytest Docker timeout in seconds (default: 300)")

    # Behaviour
    p.add_argument("--force", action="store_true", default=False,
                   help="Re-run pytest even for rows where pytest_ran=True")
    p.add_argument("--dry-run", action="store_true", default=False,
                   help="Print which rows would be processed without running anything")
    p.add_argument("--workers", type=int, default=1,
                   help="Number of parallel pytest workers (default: 1 = sequential)")
    p.add_argument("--log-level", default="INFO", choices=["DEBUG", "INFO", "WARNING"])
    return p


# ---------------------------------------------------------------------------
# Core logic
# ---------------------------------------------------------------------------


def _parse_pytest_counts(stdout: str, stderr: str) -> dict[str, Any]:
    """Parse pytest summary counts from combined stdout+stderr."""
    text = "\n".join([stdout or "", stderr or ""])
    counts: dict[str, int] = {}

    for line in reversed(text.splitlines()):
        line = line.strip()
        if not line:
            continue
        matches = list(_PYTEST_SUMMARY_ITEM_RE.finditer(line))
        if not matches:
            continue
        parsed: dict[str, int] = {}
        for match in matches:
            label = match.group("label").lower()
            if label == "error":
                label = "errors"
            parsed[label] = parsed.get(label, 0) + int(match.group("count"))
        if parsed:
            counts = parsed
            break

    total = (
        counts.get("passed", 0) + counts.get("failed", 0) + counts.get("skipped", 0)
        + counts.get("xfailed", 0) + counts.get("xpassed", 0) + counts.get("errors", 0)
    )
    if total == 0:
        collected_total: int | None = None
        for line in reversed(text.splitlines()):
            m = _PYTEST_COLLECTED_RE.search(line)
            if m:
                collected_total = int(m.group("count"))
                break
        total_or_none = collected_total
    else:
        total_or_none = total

    # Back-fill counts not on the summary line
    for key, pattern in [
        ("deselected", r"\b(\d+)\s+deselected\b"),
        ("xfailed", r"\b(\d+)\s+xfailed\b"),
        ("xpassed", r"\b(\d+)\s+xpassed\b"),
        ("errors", r"\b(\d+)\s+errors?\b"),
    ]:
        if key not in counts:
            m = re.search(pattern, text, flags=re.IGNORECASE)
            if m:
                counts[key] = int(m.group(1))

    return {
        "total": total_or_none,
        "passed": counts.get("passed"),
        "failed": counts.get("failed"),
        "skipped": counts.get("skipped"),
        "xfailed": counts.get("xfailed"),
        "xpassed": counts.get("xpassed"),
        "errors": counts.get("errors"),
        "deselected": counts.get("deselected"),
    }


def _run_pytest_for_row(
    row: dict,
    suite,
    repo_root_override: str | None,
    cfg: RunConfig,
) -> tuple[dict, str | None]:
    """Run pytest for one matrix row.  Returns (updated_row, error_msg|None)."""
    task_id = row.get("task_id", "")
    run_dir = row.get("run_dir", "")
    code_output = row.get("code_output", "")

    if not run_dir or not Path(run_dir).exists():
        return row, f"run_dir not found: {run_dir!r}"

    # Read generated code from artifact
    code_file = Path(code_output) if code_output and Path(code_output).exists() else None
    if code_file is None:
        # Fallback: look for generated_code.txt in run_dir
        fallback = Path(run_dir) / "generated_code.txt"
        if fallback.exists():
            code_file = fallback
    if code_file is None:
        return row, f"code_output not found: {code_output!r}"

    code = code_file.read_text(encoding="utf-8")
    if not code.strip():
        row.update({
            "pytest_ran": False,
            "pytest_passed": False,
            "pytest_error": "generated code is empty",
        })
        return row, "generated code is empty"

    # Load task from suite
    task = suite.task_map.get(task_id)
    if not task:
        return row, f"task {task_id!r} not in suite"
    if not task.task.target_file:
        return row, f"task {task_id!r} has no target_file"
    if not task.task.test_command:
        return row, f"task {task_id!r} has no test_command"

    # Resolve repo root: override > task YAML > None
    repo_root_str = repo_root_override or task.task.repo_root
    if not repo_root_str:
        return row, f"no repo_root for task {task_id!r} (pass --repo-root)"
    repo_root = Path(repo_root_str).expanduser().resolve()
    if not repo_root.exists():
        return row, f"repo_root does not exist: {repo_root}"

    target_file = task.task.target_file
    original_path = (repo_root / target_file).resolve()
    try:
        patched_content = apply_line_range_rewrite(
            code=code,
            original_path=original_path,
            line_start=task.task.line_start,
            line_end=task.task.line_end,
        )
    except Exception as exc:
        return row, f"could not produce patched file: {exc}"

    patched_filename = "patched_" + Path(target_file).name
    patched_host_path = Path(run_dir) / patched_filename
    patched_host_path.write_text(patched_content, encoding="utf-8")

    container_path = _container_file_path(
        workdir=cfg.pytest_docker_workdir,
        target_file=target_file,
    )
    LOGGER.info(
        "  pytest  task=%s  inject=%s→%s",
        task_id, patched_host_path, container_path,
    )
    t0 = time.time()
    pr: PytestResult
    container: str | None = None
    try:
        container = start_test_container(
            image=cfg.pytest_docker_image,
            workdir=cfg.pytest_docker_workdir,
            timeout_seconds=cfg.pytest_timeout_seconds,
        )
        docker_cp(patched_host_path, container, container_path)
        pr = run_pytest_in_docker(
            container_name=container,
            test_command=task.task.test_command,
            cfg=cfg,
        )
        if original_path.exists():
            try:
                docker_cp(original_path, container, container_path)
            except Exception:
                LOGGER.debug("restore cp failed (non-fatal)")
    except Exception as exc:
        LOGGER.exception("patch+test raised for task=%s", task_id)
        pr = PytestResult(ran=False, error=str(exc))
    finally:
        if container:
            stop_test_container(container)

    duration_ms = int((time.time() - t0) * 1000)

    # Write stdout/stderr files into run_dir (mirrors _write_artifacts behaviour)
    if pr.ran:
        run_dir_path = Path(run_dir)
        (run_dir_path / "pytest.stdout.txt").write_text(pr.stdout or "", encoding="utf-8")
        (run_dir_path / "pytest.stderr.txt").write_text(pr.stderr or "", encoding="utf-8")

    counts = _parse_pytest_counts(pr.stdout or "", pr.stderr or "")

    # Update the row dict with pytest columns
    row.update({
        "pytest_ran": pr.ran,
        "pytest_passed": pr.passed,
        "pytest_returncode": pr.returncode,
        "pytest_duration_ms": pr.duration_ms or duration_ms,
        "pytest_docker_image": pr.docker_image,
        "pytest_error": (pr.error or "")[:300],
        "pytest_stdout_file": str(Path(run_dir) / "pytest.stdout.txt") if pr.ran else "",
        "pytest_stderr_file": str(Path(run_dir) / "pytest.stderr.txt") if pr.ran else "",
        "pytest_total": counts["total"],
        "pytest_passed_count": counts["passed"],
        "pytest_failed_count": counts["failed"],
        "pytest_skipped_count": counts["skipped"],
        "pytest_xfailed_count": counts["xfailed"],
        "pytest_xpassed_count": counts["xpassed"],
        "pytest_errors_count": counts["errors"],
        "pytest_deselected_count": counts["deselected"],
    })

    status = "PASS" if pr.passed else ("FAIL" if pr.ran else "SKIP")
    LOGGER.info(
        "  → %s  ran=%s  returncode=%s  %.1fs  [%s/%s/%s]",
        status, pr.ran, pr.returncode, (time.time() - t0),
        row.get("task_id"), row.get("variant_id"), row.get("model_name"),
    )
    return row, None


def _write_csv(csv_path: Path, rows: list[dict]) -> None:
    """Write all rows back to the CSV, preserving all columns (union of all keys)."""
    if not rows:
        return
    # Build ordered fieldnames: preserve original order where possible, append new ones
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
    cfg_kwargs: dict[str, Any] = {
        "auto_apply_patch": True,  # implied for this script
        "pytest_timeout_seconds": args.pytest_timeout,
    }
    # Use suite-level Docker config if present, CLI overrides win
    if args.pytest_docker_image:
        cfg_kwargs["pytest_docker_image"] = args.pytest_docker_image
    elif suite.suite.pytest_docker_image:
        cfg_kwargs["pytest_docker_image"] = suite.suite.pytest_docker_image
    if args.pytest_docker_workdir:
        cfg_kwargs["pytest_docker_workdir"] = args.pytest_docker_workdir
    elif suite.suite.pytest_docker_workdir:
        cfg_kwargs["pytest_docker_workdir"] = suite.suite.pytest_docker_workdir
    cfg = RunConfig(**cfg_kwargs)

    # Load CSV
    with csv_path.open(encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    LOGGER.info("loaded %d rows from %s", len(rows), csv_path)

    # Parse filters
    filter_tasks = set(t.strip() for t in args.tasks.split(",") if t.strip()) if args.tasks else None
    filter_variants = set(v.strip() for v in args.variants.split(",") if v.strip()) if args.variants else None
    filter_models = set(m.strip() for m in args.models.split(",") if m.strip()) if args.models else None

    # Identify rows to process
    to_process: list[int] = []
    for i, row in enumerate(rows):
        # Filter by task/variant/model
        if filter_tasks and row.get("task_id") not in filter_tasks:
            continue
        if filter_variants and row.get("variant_id") not in filter_variants:
            continue
        if filter_models and row.get("model_name") not in filter_models:
            continue
        # Skip error rows (no generated code to test)
        if row.get("status") == "error":
            continue
        # Skip rows already tested (unless --force)
        if not args.force:
            pytest_ran = row.get("pytest_ran", "").strip().lower()
            if pytest_ran in ("true", "1", "yes"):
                continue
        # Skip rows with no run_dir
        if not row.get("run_dir"):
            continue
        to_process.append(i)

    LOGGER.info(
        "%d/%d rows need pytest  (force=%s filters: tasks=%s variants=%s models=%s)",
        len(to_process), len(rows), args.force, filter_tasks, filter_variants, filter_models,
    )

    if not to_process:
        LOGGER.info("nothing to do")
        return

    if args.dry_run:
        print(f"\nDry-run: would process {len(to_process)} rows:")
        for i in to_process:
            r = rows[i]
            print(f"  [{i+1}/{len(rows)}]  {r.get('task_id')}/{r.get('variant_id')}/{r.get('model_name')}")
        return

    # Run pytest for each row (sequential or parallel)
    import queue as _queue
    import threading

    errors: list[str] = []

    if args.workers <= 1:
        for idx, i in enumerate(to_process, 1):
            LOGGER.info("[%d/%d] task=%s variant=%s model=%s",
                        idx, len(to_process),
                        rows[i].get("task_id"), rows[i].get("variant_id"), rows[i].get("model_name"))
            rows[i], err = _run_pytest_for_row(rows[i], suite, args.repo_root, cfg)
            if err:
                LOGGER.warning("  skipped: %s", err)
                errors.append(f"{rows[i].get('task_id')}/{rows[i].get('variant_id')}: {err}")
    else:
        # Parallel: queue of indices, N worker threads
        results_lock = threading.Lock()
        started = [0]
        task_queue: _queue.Queue = _queue.Queue()
        for i in to_process:
            task_queue.put(i)

        def _worker() -> None:
            while True:
                idx = task_queue.get()
                try:
                    if idx is None:
                        return
                    with results_lock:
                        started[0] += 1
                        n = started[0]
                    LOGGER.info("[%d/%d] task=%s variant=%s model=%s",
                                n, len(to_process),
                                rows[idx].get("task_id"), rows[idx].get("variant_id"), rows[idx].get("model_name"))
                    updated_row, err = _run_pytest_for_row(rows[idx], suite, args.repo_root, cfg)
                    with results_lock:
                        rows[idx] = updated_row
                        if err:
                            errors.append(err)
                except Exception as exc:
                    LOGGER.exception("worker error on row %d", idx)
                finally:
                    task_queue.task_done()

        threads = [
            threading.Thread(target=_worker, daemon=True, name=f"worker-{i}")
            for i in range(args.workers)
        ]
        for t in threads:
            t.start()
        task_queue.join()
        for _ in threads:
            task_queue.put(None)
        for t in threads:
            t.join(timeout=5.0)

    # Write updated CSV back
    _write_csv(csv_path, rows)

    n_ran = sum(1 for i in to_process if rows[i].get("pytest_ran") in (True, "True"))
    n_pass = sum(1 for i in to_process if rows[i].get("pytest_passed") in (True, "True"))
    print(f"\n  pytest rescore complete")
    print(f"  processed: {len(to_process)} rows")
    print(f"  ran:       {n_ran}")
    print(f"  passed:    {n_pass}")
    if errors:
        print(f"  skipped:   {len(errors)} (no code / config missing)")
        for e in errors[:10]:
            print(f"    {e}")
    print(f"  CSV:       {csv_path}")


if __name__ == "__main__":
    main()
