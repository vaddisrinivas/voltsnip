#!/usr/bin/env python3
"""End-to-end integration test for the vsevals pipeline.

Brings up VoltSnip backend (Postgres + FastAPI), seeds snippets, runs a
single eval cell, validates artifacts, and optionally compares against a
golden run directory.

Two modes:
  - Default (mock):  Uses mock:default — fast, no API key, deterministic.
  - Real (--real):   Uses claudecode:claude-haiku-4-5 — live LLM, needs auth.

Usage
-----
    cd /Users/srinivasvaddi/moltsnip/vsevals

    # Fast CI smoke (mock provider, no golden)
    uv run python3 scripts/run_integration_test.py --task BUG39 --variant P0

    # With golden comparison
    uv run python3 scripts/run_integration_test.py --task BUG39 --variant P0 \
      --golden-dir vsevals_runs/matrix_20260303T042816331269Z

    # Real LLM (costs money, needs Claude Code auth)
    uv run python3 scripts/run_integration_test.py --task BUG39 --variant P0 --real
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

VSEVALS_DIR = Path(__file__).resolve().parent.parent        # …/vsevals
BACKEND_DIR = VSEVALS_DIR.parent / "backend"                # …/backend
DOCKER_COMPOSE = BACKEND_DIR / "docker-compose.yml"
SUITE_YAML = VSEVALS_DIR / "suite.yaml"
SNIPPETS_DIRS = [
    VSEVALS_DIR / "snippets" / "bug22_generic",
    VSEVALS_DIR / "snippets" / "script30",
]

INTEGRATION_PORT = 8765
BASE_URL = f"http://127.0.0.1:{INTEGRATION_PORT}"
DB_URL = "postgresql+asyncpg://user:password@127.0.0.1:5432/voltsnip"

# Colors
GREEN = "\033[92m"
RED = "\033[91m"
YELLOW = "\033[93m"
CYAN = "\033[96m"
RESET = "\033[0m"


def _log(msg: str, color: str = CYAN) -> None:
    print(f"{color}[integration]{RESET} {msg}", flush=True)


def _ok(msg: str) -> None:
    _log(f"PASS  {msg}", GREEN)


def _fail(msg: str) -> None:
    _log(f"FAIL  {msg}", RED)


def _warn(msg: str) -> None:
    _log(f"WARN  {msg}", YELLOW)


# ---------------------------------------------------------------------------
# Step 1: Prerequisites
# ---------------------------------------------------------------------------

def check_prerequisites() -> None:
    _log("Checking prerequisites...")
    errors = []
    if not shutil.which("docker"):
        errors.append("docker not found on PATH")
    if not BACKEND_DIR.is_dir():
        errors.append(f"backend dir not found: {BACKEND_DIR}")
    if not DOCKER_COMPOSE.is_file():
        errors.append(f"docker-compose.yml not found: {DOCKER_COMPOSE}")
    if not SUITE_YAML.is_file():
        errors.append(f"suite.yaml not found: {SUITE_YAML}")
    for d in SNIPPETS_DIRS:
        if not d.is_dir():
            errors.append(f"snippets dir not found: {d}")
    if errors:
        for e in errors:
            _fail(e)
        sys.exit(1)
    _ok("All prerequisites satisfied")


# ---------------------------------------------------------------------------
# Step 2: Start VoltSnip backend
# ---------------------------------------------------------------------------

def start_database() -> None:
    _log("Starting Postgres (pgvector)...")
    subprocess.run(
        ["docker", "compose", "-f", str(DOCKER_COMPOSE), "up", "-d", "db"],
        check=True, capture_output=True,
    )
    # Wait for DB readiness
    for attempt in range(30):
        result = subprocess.run(
            ["docker", "compose", "-f", str(DOCKER_COMPOSE),
             "exec", "-T", "db", "pg_isready", "-U", "user", "-d", "voltsnip"],
            capture_output=True,
        )
        if result.returncode == 0:
            _ok(f"Postgres ready (attempt {attempt + 1})")
            return
        time.sleep(1)
    _fail("Postgres failed to become ready after 30s")
    sys.exit(1)


def run_migrations() -> None:
    _log("Running alembic migrations...")
    env = {**os.environ, "DATABASE_URL": DB_URL}
    result = subprocess.run(
        ["uv", "run", "alembic", "upgrade", "head"],
        cwd=str(BACKEND_DIR), env=env, capture_output=True, text=True,
    )
    if result.returncode != 0:
        _fail(f"Alembic migration failed:\n{result.stderr}")
        sys.exit(1)
    _ok("Migrations applied")


def start_backend() -> subprocess.Popen:
    _log(f"Starting uvicorn on port {INTEGRATION_PORT}...")
    env = {
        **os.environ,
        "DATABASE_URL": DB_URL,
        "STORAGE_PROVIDER": "local",
        "STORAGE_URI": str(BACKEND_DIR / "local_storage"),
        "EMBEDDINGS_ENABLED": "false",  # No GPU needed for integration test
        "STATS_ENABLED": "false",
    }
    proc = subprocess.Popen(
        ["uv", "run", "uvicorn", "app.main:app",
         "--host", "127.0.0.1", "--port", str(INTEGRATION_PORT)],
        cwd=str(BACKEND_DIR), env=env,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    # Poll health endpoint
    for attempt in range(60):
        try:
            req = urllib.request.Request(f"{BASE_URL}/health")
            with urllib.request.urlopen(req, timeout=2):
                _ok(f"Backend ready at {BASE_URL} (attempt {attempt + 1})")
                return proc
        except Exception:
            if proc.poll() is not None:
                stderr = proc.stderr.read().decode() if proc.stderr else ""
                _fail(f"Backend process exited prematurely:\n{stderr}")
                sys.exit(1)
            time.sleep(1)
    _fail("Backend failed to become ready after 60s")
    proc.terminate()
    sys.exit(1)


# ---------------------------------------------------------------------------
# Step 3: Seed snippets
# ---------------------------------------------------------------------------

def seed_snippets() -> None:
    _log("Seeding snippets...")
    seed_script = VSEVALS_DIR / "scripts" / "seed_snippets.py"
    for snippets_dir in SNIPPETS_DIRS:
        _log(f"  Seeding from {snippets_dir.name}/...")
        result = subprocess.run(
            ["uv", "run", "python3", str(seed_script),
             "--base-url", BASE_URL, "--snippets-dir", str(snippets_dir)],
            cwd=str(VSEVALS_DIR), capture_output=True, text=True,
        )
        if result.returncode != 0:
            _fail(f"Seed failed for {snippets_dir.name}:\n{result.stderr}")
            sys.exit(1)
    _ok("All snippets seeded")


# ---------------------------------------------------------------------------
# Step 4: Run eval
# ---------------------------------------------------------------------------

def run_eval(
    task_id: str,
    variant_id: str,
    model_name: str,
    output_dir: Path,
    suite_path: Path,
    real_mode: bool = False,
) -> object:
    _log(f"Running eval: {task_id} / {variant_id} / {model_name}")
    # Import here so the script can do prereq checks without the vsevals package
    from vsevals.runner import run_one
    from vsevals.models import RunConfig

    # In real mode use a real judge so constraint scoring works properly;
    # mock judge returns canned output the constraint parser can't interpret.
    judge = "anthropic:claude-haiku-4-5" if real_mode else "mock:default"
    _log(f"  scoring_judge_model={judge}")

    cfg = RunConfig(
        voltsnip_base_url=BASE_URL,
        scoring_judge_model=judge,
        auto_apply_patch=False,
        skip_scoring=False,
    )
    result = run_one(
        task_id=task_id,
        variant_id=variant_id,
        model_name=model_name,
        suite_path=str(suite_path),
        output_dir=str(output_dir),
        cfg=cfg,
    )
    _ok(f"Eval completed — status={result.status}")
    return result


# ---------------------------------------------------------------------------
# Step 5: Validate artifacts
# ---------------------------------------------------------------------------

def validate_artifacts(
    result: object,
    output_dir: Path,
    real_mode: bool,
    variant_id: str,
) -> list[str]:
    failures = []

    def _check(cond: bool, msg: str) -> None:
        if cond:
            _ok(msg)
        else:
            _fail(msg)
            failures.append(msg)

    _log("Validating artifacts...")

    # Check run directory exists
    run_dir = Path(result.artifacts.run_dir)  # type: ignore[attr-defined]
    _check(run_dir.is_dir(), f"Run directory exists: {run_dir.name}")

    # Check expected files
    expected_files = ["full_dump.json", "summary_dump.json", "prompt.json"]
    for fname in expected_files:
        _check((run_dir / fname).is_file(), f"Artifact exists: {fname}")

    # Parse and validate full_dump.json
    dump_path = run_dir / "full_dump.json"
    if dump_path.is_file():
        dump = json.loads(dump_path.read_text())

        _check(dump.get("status") == "ok", "status == 'ok'")
        _check(dump.get("task_id") == result.task_id, f"task_id matches: {result.task_id}")  # type: ignore[attr-defined]
        _check(dump.get("variant_id") == result.variant_id, f"variant_id matches: {result.variant_id}")  # type: ignore[attr-defined]

        # Parsed output
        parsed = dump.get("parsed_output", {})
        has_code = isinstance(parsed.get("code"), str) and len(parsed["code"]) > 0
        if real_mode:
            _check(has_code, "parsed_output.code is non-empty (real mode)")
        else:
            _ok(f"parsed_output.code present (len={len(parsed.get('code', ''))})")

        # Token usage
        tokens = dump.get("token_usage", {})
        _check(isinstance(tokens.get("total_tokens"), int), "token_usage.total_tokens is int")
        if real_mode:
            _check(tokens.get("prompt_tokens", 0) > 0, "token_usage.prompt_tokens > 0 (real mode)")

        # Timings
        timings = dump.get("timings", {})
        _check(timings.get("started_at") is not None, "timings.started_at present")
        _check(timings.get("finished_at") is not None, "timings.finished_at present")

        # Score
        score = dump.get("score")
        _check(score is not None, "score is present")
        if score:
            _check("passed" in score, "score.passed present")
            _check("overall_score" in score, "score.overall_score present")
            # Score > 0 only expected for context-enabled variants (P2+).
            # P0-P1 are designed to fail on composition bugs like BUG39.
            has_context = variant_id.upper() not in ("P0", "P1")
            if real_mode and has_context:
                _check(score.get("overall_score", 0) > 0, "score.overall_score > 0 (real + context variant)")
            elif real_mode:
                _log(f"  score.overall_score = {score.get('overall_score')} (P0-P1: low score expected)")

    return failures


# ---------------------------------------------------------------------------
# Step 6: Golden comparison
# ---------------------------------------------------------------------------

def compare_golden(result: object, golden_dir: Path) -> list[str]:
    _log(f"Comparing with golden: {golden_dir}")
    warnings = []

    task_id = result.task_id.lower()  # type: ignore[attr-defined]
    variant_id = result.variant_id.lower()  # type: ignore[attr-defined]
    model_name = result.model_name.replace(":", "_")  # type: ignore[attr-defined]

    # Find matching golden run directory
    runs_dir = golden_dir / "runs"
    if not runs_dir.is_dir():
        _warn(f"No runs/ directory in golden dir")
        return ["golden runs/ dir missing"]

    golden_run = None
    for d in runs_dir.iterdir():
        if not d.is_dir():
            continue
        name = d.name.lower()
        if f"__{task_id}__" in name and f"__{variant_id}__" in name:
            golden_run = d
            break

    if golden_run is None:
        _warn(f"No golden run found for {task_id}/{variant_id}")
        return [f"no golden run for {task_id}/{variant_id}"]

    _log(f"  Golden run: {golden_run.name}")

    golden_dump = golden_run / "full_dump.json"
    new_dump_path = Path(result.artifacts.run_dir) / "full_dump.json"  # type: ignore[attr-defined]

    if not golden_dump.is_file():
        _warn("Golden full_dump.json missing")
        return ["golden full_dump.json missing"]
    if not new_dump_path.is_file():
        _warn("New full_dump.json missing")
        return ["new full_dump.json missing"]

    golden = json.loads(golden_dump.read_text())
    new = json.loads(new_dump_path.read_text())

    # Structural comparison: same top-level keys
    golden_keys = set(golden.keys())
    new_keys = set(new.keys())
    missing = golden_keys - new_keys
    extra = new_keys - golden_keys
    if missing:
        _warn(f"Missing keys vs golden: {missing}")
        warnings.append(f"missing keys: {missing}")
    if extra:
        _warn(f"Extra keys vs golden: {extra}")
        warnings.append(f"extra keys: {extra}")
    if not missing and not extra:
        _ok("Top-level keys match golden")

    # Score structure
    g_score = golden.get("score", {})
    n_score = new.get("score", {})
    if g_score and n_score:
        g_score_keys = set(g_score.keys()) if isinstance(g_score, dict) else set()
        n_score_keys = set(n_score.keys()) if isinstance(n_score, dict) else set()
        if g_score_keys == n_score_keys:
            _ok("Score structure matches golden")
        else:
            _warn(f"Score keys differ: golden={g_score_keys}, new={n_score_keys}")
            warnings.append("score structure differs")

    # Artifact file comparison
    golden_files = {f.name for f in golden_run.iterdir() if f.is_file()}
    new_run_dir = Path(result.artifacts.run_dir)  # type: ignore[attr-defined]
    new_files = {f.name for f in new_run_dir.iterdir() if f.is_file()}
    files_missing = golden_files - new_files
    files_extra = new_files - golden_files
    if files_missing:
        _warn(f"Missing artifact files vs golden: {files_missing}")
        warnings.append(f"missing files: {files_missing}")
    if files_extra:
        # Extra files are fine (new features)
        _log(f"  Extra files vs golden (OK): {files_extra}")
    if not files_missing:
        _ok("All golden artifact files present")

    return warnings


# ---------------------------------------------------------------------------
# Step 7: Cleanup
# ---------------------------------------------------------------------------

def cleanup(proc: subprocess.Popen | None, keep_artifacts: bool, output_dir: Path) -> None:
    _log("Cleaning up...")

    # Kill uvicorn
    if proc and proc.poll() is None:
        _log("  Stopping backend...")
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()

    # Stop DB
    _log("  Stopping database...")
    subprocess.run(
        ["docker", "compose", "-f", str(DOCKER_COMPOSE), "stop", "db"],
        capture_output=True,
    )

    if not keep_artifacts and output_dir.exists():
        _log(f"  Removing artifacts: {output_dir}")
        shutil.rmtree(output_dir, ignore_errors=True)

    _ok("Cleanup complete")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="E2E integration test for vsevals pipeline",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--task", default="BUG39", help="Task ID (default: BUG39)")
    parser.add_argument("--variant", default="P0", help="Variant ID (default: P0)")
    parser.add_argument("--suite", type=Path, default=SUITE_YAML, help="Suite YAML path")
    parser.add_argument("--golden-dir", type=Path, default=None,
                        help="Golden run directory for comparison")
    parser.add_argument("--real", action="store_true",
                        help="Use live LLM (claudecode:claude-haiku-4-5) instead of mock")
    parser.add_argument("--keep-artifacts", action="store_true",
                        help="Keep output artifacts after test")
    parser.add_argument("--output-dir", type=Path, default=None,
                        help="Output directory (default: tempdir)")
    args = parser.parse_args()

    model = "claudecode:claude-haiku-4-5" if args.real else "mock:default"
    output_dir = args.output_dir or Path(tempfile.mkdtemp(prefix="vsevals_integ_"))

    _log(f"Integration test: {args.task} / {args.variant} / {model}")
    _log(f"Output: {output_dir}")

    backend_proc = None
    failures = []
    golden_warnings = []

    try:
        # Step 1: Prerequisites
        check_prerequisites()

        # Step 2: Start backend
        start_database()
        run_migrations()
        backend_proc = start_backend()

        # Step 3: Seed snippets
        seed_snippets()

        # Step 4: Run eval
        result = run_eval(
            task_id=args.task,
            variant_id=args.variant,
            model_name=model,
            output_dir=output_dir,
            suite_path=args.suite,
            real_mode=args.real,
        )

        # Step 5: Validate artifacts
        failures = validate_artifacts(result, output_dir, real_mode=args.real, variant_id=args.variant)

        # Step 6: Golden comparison
        if args.golden_dir:
            golden_warnings = compare_golden(result, args.golden_dir)

    except KeyboardInterrupt:
        _warn("Interrupted by user")
        failures.append("interrupted")
    except Exception as exc:
        _fail(f"Unexpected error: {exc}")
        import traceback
        traceback.print_exc()
        failures.append(str(exc))
    finally:
        # Step 7: Cleanup
        keep = args.keep_artifacts or bool(failures)
        cleanup(backend_proc, keep, output_dir)

    # Summary
    print()
    _log("=" * 60)
    if failures:
        _fail(f"{len(failures)} validation failure(s):")
        for f in failures:
            print(f"    - {f}")
        if golden_warnings:
            _warn(f"{len(golden_warnings)} golden comparison warning(s)")
        sys.exit(1)
    else:
        if golden_warnings:
            _warn(f"{len(golden_warnings)} golden comparison warning(s) (non-blocking):")
            for w in golden_warnings:
                print(f"    - {w}")
        _ok("All checks passed!")
        sys.exit(0)


if __name__ == "__main__":
    main()
