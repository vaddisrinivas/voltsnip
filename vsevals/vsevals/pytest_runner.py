"""Docker-based pytest runner.

Runs the project's test suite inside a Docker container, mounting the
isolated overlay directory as the workspace.  The original repository is
never touched.

Public API
----------
  run_pytest_in_docker(
      test_command, overlay_root, cfg
  ) -> PytestResult

Docker command produced
-----------------------
  docker run --rm
    -v <overlay_root>:<workdir>
    -w <workdir>
    <image>
    <test_command...>

The test_command comes from task.task.test_command in the suite YAML, e.g.:
  "pytest tests/unit/test_retry.py -x -q"

Prerequisites
-------------
  - Docker daemon must be running.
  - The Docker image must have Python + pytest (and project deps) pre-installed.
  - Dockerfile example:
      FROM python:3.12-slim
      WORKDIR /workspace
      COPY requirements.txt .
      RUN pip install --no-cache-dir -r requirements.txt
      # No ENTRYPOINT; we pass the command at run time.

Image build hint
----------------
  docker build -t moltsnip-pytest:latest -f Dockerfile.pytest .
"""

from __future__ import annotations

import logging
import shlex
import subprocess
import time
from pathlib import Path

from vsevals.models import PytestResult, RunConfig

LOGGER = logging.getLogger(__name__)


def run_pytest_in_docker(
    *,
    test_command: str,
    overlay_root: Path,
    cfg: RunConfig,
) -> PytestResult:
    """Run `test_command` inside Docker with `overlay_root` mounted as the workspace.

    Parameters
    ----------
    test_command:
        Shell command string to run inside the container, e.g.
        ``"pytest tests/ -x -q"``.
    overlay_root:
        Absolute path to the isolated overlay directory that will be mounted
        read-write as the container's workdir.
    cfg:
        RunConfig — provides docker image, workdir, and timeout settings.

    Returns
    -------
    PytestResult
    """
    image = cfg.pytest_docker_image
    workdir = cfg.pytest_docker_workdir
    timeout = cfg.pytest_timeout_seconds

    if not overlay_root.exists():
        return PytestResult(
            ran=False,
            error=f"overlay_root does not exist: {overlay_root}",
            docker_image=image,
            overlay_path=str(overlay_root),
        )

    cmd = _build_docker_command(
        test_command=test_command,
        overlay_root=overlay_root,
        image=image,
        workdir=workdir,
    )
    LOGGER.info(
        "docker pytest  image=%s  overlay=%s  cmd=%s",
        image, overlay_root, " ".join(cmd),
    )

    t0 = time.perf_counter()
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        duration_ms = int((time.perf_counter() - t0) * 1000)
        passed = proc.returncode == 0
        LOGGER.info(
            "docker pytest done  returncode=%d  passed=%s  duration_ms=%d",
            proc.returncode, passed, duration_ms,
        )
        return PytestResult(
            ran=True,
            returncode=proc.returncode,
            passed=passed,
            stdout=proc.stdout[:8192],
            stderr=proc.stderr[:4096],
            duration_ms=duration_ms,
            docker_image=image,
            overlay_path=str(overlay_root),
        )
    except subprocess.TimeoutExpired:
        duration_ms = int((time.perf_counter() - t0) * 1000)
        LOGGER.warning("docker pytest timed out  timeout=%ds", timeout)
        return PytestResult(
            ran=True,
            returncode=-1,
            passed=False,
            error=f"timed out after {timeout}s",
            duration_ms=duration_ms,
            docker_image=image,
            overlay_path=str(overlay_root),
        )
    except FileNotFoundError:
        duration_ms = int((time.perf_counter() - t0) * 1000)
        msg = "docker not found — is Docker installed and running?"
        LOGGER.error(msg)
        return PytestResult(
            ran=False,
            error=msg,
            duration_ms=duration_ms,
            docker_image=image,
            overlay_path=str(overlay_root),
        )
    except Exception as exc:
        duration_ms = int((time.perf_counter() - t0) * 1000)
        LOGGER.exception("docker pytest failed unexpectedly")
        return PytestResult(
            ran=False,
            error=str(exc),
            duration_ms=duration_ms,
            docker_image=image,
            overlay_path=str(overlay_root),
        )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _build_docker_command(
    *,
    test_command: str,
    overlay_root: Path,
    image: str,
    workdir: str,
) -> list[str]:
    """Build the `docker run` command list.

    overlay_root is always mounted at /workspace.  workdir sets the working
    directory inside the container (may be /workspace or a subpath).

    The overlay directory is mounted read-write so pytest can write .pytest_cache
    and coverage files without issues.  The container is removed after exit (--rm).
    """
    cmd: list[str] = [
        "docker", "run", "--rm",
        "--volume", f"{overlay_root.resolve()}:/workspace",
        "--workdir", workdir,
        # Security: no network access needed for pure unit tests
        "--network", "none",
        image,
    ]
    # Append the test command — split to avoid shell injection
    cmd.extend(shlex.split(test_command))
    return cmd
