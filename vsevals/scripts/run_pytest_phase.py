#!/usr/bin/env python3
"""Phase-2 pytest runner: apply patches and run Docker pytest on completed matrix runs.

Designed to be run AFTER run_matrix.py finishes code generation and scoring.
Reads the matrix_results.csv to find runs that haven't had pytest run yet,
applies each generated patch to an isolated overlay, runs pytest in Docker,
then updates full_dump.json / summary_dump.json and the CSV in-place.

Usage
-----
# Run pytest on all un-tested runs in a matrix dir
python scripts/run_pytest_phase.py \\
    --matrix-dir ./vsevals_runs/matrix_20260225T... \\
    --suite voltsnip-evals/suite.yaml

# With a specific docker image and timeout
python scripts/run_pytest_phase.py \\
    --matrix-dir ./vsevals_runs/matrix_20260225T... \\
    --suite voltsnip-evals/suite.yaml \\
    --docker-image moltsnip-pytest:latest \\
    --pytest-timeout 120

# Re-run pytest even on runs that already have a result (force)
python scripts/run_pytest_phase.py \\
    --matrix-dir ./vsevals_runs/matrix_20260225T... \\
    --suite voltsnip-evals/suite.yaml \\
    --force
"""

from __future__ import annotations

import argparse
import csv
import json
import logging
import sys
import time
from pathlib import Path
from typing import Any

_here = Path(__file__).resolve().parent.parent
if str(_here) not in sys.path:
    sys.path.insert(0, str(_here))

from vsevals.loader import load_suite
from vsevals.models import RunConfig, RunResult
from vsevals.patching import apply_rewrite, cleanup_overlay, materialize_overlay
from vsevals.pytest_runner import run_pytest_in_docker
from vsevals.runner import _compute_mount_root, _resolve_repo_root

LOGGER = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Phase-2: run pytest on completed matrix code-gen runs.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    p.add_argument("--matrix-dir", required=True, help="Path to the matrix output dir from run_matrix.py")
    p.add_argument("--suite", required=True, help="Path to suite YAML (same one used in Phase 1)")
    p.add_argument("--repo-root", default=None, help="Override repo root for all tasks")
    p.add_argument("--docker-image", default=None, help="Docker image (default: from usecase.yaml or moltsnip-pytest:latest)")
    p.add_argument("--pytest-timeout", type=int, default=300, help="Seconds per pytest run (default: 300)")
    p.add_argument("--force", action="store_true", default=False,
                   help="Re-run pytest even on rows that already have a pytest result")
    p.add_argument("--tasks", default=None, help="Comma-separated task IDs to limit (default: all)")
    p.add_argument("--variants", default=None, help="Comma-separated variant IDs to limit (default: all)")
    p.add_argument("--log-level", default="INFO", choices=["DEBUG", "INFO", "WARNING"])
    return p


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

    matrix_dir = Path(args.matrix_dir).expanduser().resolve()
    if not matrix_dir.exists():
        parser.error(f"matrix-dir not found: {matrix_dir}")

    csv_path = matrix_dir / "matrix_results.csv"
    if not csv_path.exists():
        parser.error(f"matrix_results.csv not found in {matrix_dir}")

    suite = load_suite(args.suite)

    task_filter = {t.strip() for t in args.tasks.split(",")} if args.tasks else None
    variant_filter = {v.strip() for v in args.variants.split(",")} if args.variants else None

    cfg_kwargs: dict[str, Any] = dict(
        auto_apply_patch=True,
        pytest_timeout_seconds=args.pytest_timeout,
        unapply_patch_after_test=True,
    )
    if args.docker_image:
        cfg_kwargs["pytest_docker_image"] = args.docker_image

    # Let suite override docker settings
    base_cfg = RunConfig(**cfg_kwargs)
    if suite.suite.pytest_docker_image and base_cfg.pytest_docker_image == "moltsnip-pytest:latest":
        base_cfg = base_cfg.model_copy(update={"pytest_docker_image": suite.suite.pytest_docker_image})
    if suite.suite.pytest_docker_workdir and base_cfg.pytest_docker_workdir == "/workspace":
        base_cfg = base_cfg.model_copy(update={"pytest_docker_workdir": suite.suite.pytest_docker_workdir})

    # Load all CSV rows (we'll update and rewrite at the end)
    rows = _load_csv(csv_path)
    LOGGER.info("loaded %d rows from %s", len(rows), csv_path)

    # Filter to eligible rows
    eligible = [
        r for r in rows
        if r.get("status") == "ok"
        and r.get("run_dir")
        and r.get("full_dump_json")
        and (args.force or not _truthy(r.get("pytest_ran")))
        and (task_filter is None or r.get("task_id") in task_filter)
        and (variant_filter is None or r.get("variant_id") in variant_filter)
    ]
    LOGGER.info("%d runs eligible for pytest (force=%s)", len(eligible), args.force)

    ok_count = 0
    fail_count = 0
    skip_count = len(rows) - len(eligible)

    for i, row in enumerate(eligible, 1):
        task_id = row["task_id"]
        variant_id = row["variant_id"]
        model_name = row["model_name"]
        full_dump_path = Path(row["full_dump_json"])

        LOGGER.info("[%d/%d] task=%s variant=%s model=%s", i, len(eligible), task_id, variant_id, model_name)
        t0 = time.time()

        suite_task = suite.task_map.get(task_id)
        if suite_task is None:
            LOGGER.warning("  task %s not found in suite — skipping", task_id)
            skip_count += 1
            continue

        if not full_dump_path.exists():
            LOGGER.warning("  full_dump.json missing at %s — skipping", full_dump_path)
            skip_count += 1
            continue

        # Load the RunResult from the dump
        try:
            run_result = RunResult.model_validate(json.loads(full_dump_path.read_text(encoding="utf-8")))
        except Exception as exc:
            LOGGER.error("  failed to load RunResult from %s: %s", full_dump_path, exc)
            fail_count += 1
            continue

        code = run_result.parsed_output.code
        if not code.strip():
            LOGGER.info("  generated code is empty — skipping pytest")
            skip_count += 1
            continue

        # Resolve repo root
        repo_root = _resolve_repo_root(args.repo_root or suite_task.task.repo_root, suite_path=args.suite)
        if not repo_root:
            LOGGER.warning("  no repo_root for task %s — skipping", task_id)
            skip_count += 1
            continue

        # Run patch + pytest
        pytest_result = _run_patch_and_test(
            run_result=run_result,
            task=suite_task,
            repo_root=repo_root,
            cfg=base_cfg,
        )
        elapsed = time.time() - t0

        status_str = "pass" if pytest_result.passed else ("fail" if pytest_result.ran else f"skip({pytest_result.error or ''})")
        LOGGER.info("  → pytest=%s  %.1fs", status_str, elapsed)

        if pytest_result.ran and pytest_result.passed:
            ok_count += 1
        else:
            fail_count += 1

        # Update run_result and re-write artifacts
        run_result.pytest_result = pytest_result
        _update_artifacts(run_result)

        # Update row in-place for CSV rewrite
        row.update(_pytest_result_to_cols(run_result))

    # Rewrite the full CSV with updated rows
    _write_csv(csv_path, rows)
    LOGGER.info("CSV updated: %s", csv_path)

    # Print summary
    total = len(eligible)
    print(f"\nPhase-2 pytest complete.")
    print(f"  Ran:         {total}")
    print(f"  Passed:      {ok_count}")
    print(f"  Failed:      {fail_count}")
    print(f"  Skipped:     {skip_count}")
    print(f"  Results:     {matrix_dir}")


# ---------------------------------------------------------------------------
# Patch + Docker pytest (mirrors runner._run_patch_and_test)
# ---------------------------------------------------------------------------


def _run_patch_and_test(*, run_result: RunResult, task: Any, repo_root: Path, cfg: RunConfig) -> Any:
    from vsevals.models import PytestResult

    target_file = task.task.target_file
    test_command = task.task.test_command

    if not target_file:
        return PytestResult(ran=False, error="no target_file configured for task — cannot apply patch")
    if not test_command:
        return PytestResult(ran=False, error="no test_command configured for task — nothing to run")

    code = run_result.parsed_output.code
    if not code.strip():
        return PytestResult(ran=False, error="generated code is empty — skipping pytest")

    overlay_root = Path(run_result.artifacts.run_dir) / "_pytest_overlay"
    mount_root = _compute_mount_root(repo_root=repo_root, docker_workdir=cfg.pytest_docker_workdir)

    try:
        LOGGER.debug("overlay  target=%s  mount=%s  overlay=%s", target_file, mount_root, overlay_root)
        materialize_overlay(repo_root=mount_root, overlay_root=overlay_root)
        apply_rewrite(
            code=code,
            target_file=target_file,
            repo_root=repo_root,
            overlay_root=overlay_root,
            mount_root=mount_root,
            line_start=task.task.line_start,
            line_end=task.task.line_end,
        )
        result = run_pytest_in_docker(
            test_command=test_command,
            overlay_root=overlay_root,
            cfg=cfg,
        )
    except Exception as exc:
        LOGGER.exception("patch+test failed  task=%s", task.id)
        result = PytestResult(ran=False, error=str(exc), overlay_path=str(overlay_root))
    finally:
        if cfg.unapply_patch_after_test:
            cleanup_overlay(overlay_root)

    return result


# ---------------------------------------------------------------------------
# Artifact helpers
# ---------------------------------------------------------------------------


def _update_artifacts(run_result: RunResult) -> None:
    """Overwrite full_dump.json and summary_dump.json with updated pytest_result."""
    pr = run_result.pytest_result

    # full_dump — overwrite entirely
    Path(run_result.artifacts.full_dump_json).write_text(
        json.dumps(run_result.model_dump(mode="json"), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    # summary_dump — patch pytest_result key only
    summary_path = Path(run_result.artifacts.summary_dump_json)
    try:
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
    except Exception:
        summary = {}
    summary["pytest_result"] = pr.model_dump(mode="json") if pr else None
    summary_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")

    # pytest stdout/stderr files
    if pr and pr.ran:
        run_dir = Path(run_result.artifacts.run_dir)
        (run_dir / "pytest.stdout.txt").write_text(pr.stdout or "", encoding="utf-8")
        (run_dir / "pytest.stderr.txt").write_text(pr.stderr or "", encoding="utf-8")


def _pytest_result_to_cols(run_result: RunResult) -> dict:
    """Return the CSV columns that change after pytest runs."""
    pr = run_result.pytest_result
    if not pr:
        return {}
    from scripts.run_matrix import _parse_pytest_counts  # type: ignore[import]

    pytest_counts = _parse_pytest_counts(pr.stdout, pr.stderr)
    m = run_result.summary_metrics
    err = run_result.error
    rate_limit_count = m.voltsnip_rate_limit_count + (1 if err and err.error_class == "RATE_LIMIT_ERROR" else 0)
    timeout_count = m.voltsnip_timeout_count + (1 if err and err.error_class == "TIMEOUT" else 0)
    if pr.error and ("timeout" in pr.error.lower() or "timed out" in pr.error.lower()):
        timeout_count += 1
    mcp_error_count = sum(
        1
        for trace in run_result.tool_traces
        if trace.error and (
            "mcp" in (trace.error or "").lower()
            or "voltsnip" in (trace.tool_name or "").lower()
            or "fetch" in (trace.tool_name or "").lower()
        )
    )
    if err and "mcp" in (err.message or "").lower():
        mcp_error_count += 1

    cols: dict = {
        "pytest_ran": pr.ran,
        "pytest_passed": pr.passed,
        "pytest_returncode": pr.returncode,
        "pytest_duration_ms": pr.duration_ms,
        "pytest_total": pytest_counts["total"],
        "pytest_passed_count": pytest_counts["passed"],
        "pytest_failed_count": pytest_counts["failed"],
        "pytest_skipped_count": pytest_counts["skipped"],
        "pytest_xfailed_count": pytest_counts["xfailed"],
        "pytest_xpassed_count": pytest_counts["xpassed"],
        "pytest_errors_count": pytest_counts["errors"],
        "pytest_deselected_count": pytest_counts["deselected"],
        "pytest_docker_image": pr.docker_image,
        "pytest_error": (pr.error or "")[:300],
        "provider_retry_count": m.voltsnip_retry_count,
        "voltsnip_retry_count": m.voltsnip_retry_count,
        "voltsnip_rate_limit_count": m.voltsnip_rate_limit_count,
        "voltsnip_timeout_count": m.voltsnip_timeout_count,
        "voltsnip_error_count": m.voltsnip_error_count,
        "rate_limit_count": int(rate_limit_count),
        "timeout_count": int(timeout_count),
        "mcp_error_count": int(mcp_error_count),
    }
    if pr.ran:
        cols["pytest_stdout_file"] = run_result.artifacts.run_dir + "/pytest.stdout.txt"
        cols["pytest_stderr_file"] = run_result.artifacts.run_dir + "/pytest.stderr.txt"
    return cols


# ---------------------------------------------------------------------------
# CSV helpers
# ---------------------------------------------------------------------------


def _load_csv(path: Path) -> list[dict]:
    rows: list[dict] = []
    with path.open(encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append(dict(row))
    return rows


def _write_csv(path: Path, rows: list[dict]) -> None:
    """Rewrite the CSV in-place preserving canonical column order."""
    # Import canonical columns from run_matrix so the schema stays in sync
    from scripts.run_matrix import _CANONICAL_COLUMNS  # type: ignore[import]

    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=_CANONICAL_COLUMNS,
            extrasaction="ignore",
            restval="",
        )
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def _truthy(val: object) -> bool:
    if isinstance(val, bool):
        return val
    if isinstance(val, str):
        return val.strip().lower() in ("true", "1", "yes")
    return bool(val)


if __name__ == "__main__":
    main()
