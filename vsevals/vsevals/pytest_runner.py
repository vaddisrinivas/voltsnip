"""Docker primitives for pytest execution.

Thin layer over Docker CLI.  Container lifecycle is the caller's responsibility.

Public API
----------
  start_test_container(image, workdir, timeout_seconds) -> str
      docker run -d ... sleep <n>   returns container name

  stop_test_container(container_name) -> None
      docker rm -f <name>           best-effort

  docker_cp(src_host, container_name, container_path) -> None
      docker cp <src> <name>:<path>  raises on failure

  run_pytest_in_docker(container_name, test_command, cfg) -> PytestResult
      docker exec <name> pytest ...  captures stdout/stderr

Typical caller pattern (runner._run_patch_and_test):
------------------------------------------------------
  container = start_test_container(image=..., workdir=..., timeout_seconds=...)
  try:
      docker_cp(patched_file, container, container_path)       # inject
      result = run_pytest_in_docker(container, test_command, cfg)
      docker_cp(original_file, container, container_path)      # restore
  finally:
      stop_test_container(container)
"""

from __future__ import annotations

import logging
import shlex
import subprocess
import time
import uuid
from pathlib import Path

from vsevals.models import PytestResult, RunConfig

LOGGER = logging.getLogger(__name__)


def start_test_container(
    *,
    image: str,
    workdir: str,
    timeout_seconds: int,
    host_workdir: str | None = None,
) -> str:
    """Start a Docker container in the background and return its name.

    The container runs ``sleep <timeout+60>`` so it stays alive long enough
    for docker exec to complete.

    Parameters
    ----------
    host_workdir:
        If provided, bind-mount this host directory at ``workdir`` inside the
        container (read-write).  Use this to expose the full project overlay so
        pytest can import project modules and find test files.
    """
    name = f"moltsnip-pytest-{uuid.uuid4().hex[:12]}"
    cmd = [
        "docker", "run", "-d",
        "--name", name,
        "--workdir", workdir,
        "--network", "none",
    ]
    if host_workdir:
        cmd.extend(["-v", f"{host_workdir}:{workdir}"])
    # Mount the host uv cache read-only so `uv run pytest` can resolve
    # pure-Python packages (pytest, hatchling, etc.) offline.  The cache
    # contains py3-none-any wheels that are platform-independent.
    try:
        uv_cache = subprocess.run(
            ["uv", "cache", "dir"], capture_output=True, text=True, check=True,
        ).stdout.strip()
        if uv_cache and Path(uv_cache).is_dir():
            cmd.extend(["-v", f"{uv_cache}:{uv_cache}",
                        "-e", f"UV_CACHE_DIR={uv_cache}"])
            LOGGER.debug("mounting uv cache  host=%s", uv_cache)
    except Exception:
        pass  # uv not on PATH or cache unavailable; fall through
    cmd.extend([image, "sleep", str(timeout_seconds + 60)])
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"docker run failed: {result.stderr.strip()}")
    LOGGER.debug("container started  name=%s  image=%s  host_workdir=%s", name, image, host_workdir)
    return name


def stop_test_container(container_name: str) -> None:
    """Remove a running test container (best-effort, ignores errors)."""
    subprocess.run(["docker", "rm", "-f", container_name], capture_output=True, check=False)
    LOGGER.debug("container removed  name=%s", container_name)


def docker_cp(src_host: Path, container_name: str, container_path: str) -> None:
    """Copy a file from the host into a running container.

    Ensures the parent directory exists inside the container before copying.
    Raises RuntimeError if mkdir or cp fails.
    """
    parent = str(Path(container_path).parent)
    mkdir_result = subprocess.run(
        ["docker", "exec", container_name, "mkdir", "-p", parent],
        capture_output=True,
        text=True,
    )
    if mkdir_result.returncode != 0:
        raise RuntimeError(
            f"docker exec mkdir -p {parent} in {container_name} failed: "
            f"{mkdir_result.stderr.strip()}"
        )

    result = subprocess.run(
        ["docker", "cp", str(src_host.resolve()), f"{container_name}:{container_path}"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"docker cp {src_host} → {container_name}:{container_path} failed: "
            f"{result.stderr.strip()}"
        )
    LOGGER.debug("docker cp  src=%s  dst=%s:%s", src_host, container_name, container_path)


def run_pytest_in_docker(
    *,
    container_name: str,
    test_command: str,
    cfg: RunConfig,
) -> PytestResult:
    """Run pytest in an already-running container via docker exec.

    The container must already be started (start_test_container) and have
    the target file already copied in (docker_cp).
    """
    image = cfg.pytest_docker_image
    timeout = cfg.pytest_timeout_seconds

    test_args = _resolve_test_command_args(test_command)
    exec_cmd = _build_exec_command(container_name=container_name, test_args=test_args)
    LOGGER.info("docker exec  container=%s  cmd=%s", container_name, " ".join(exec_cmd[2:]))

    t0 = time.perf_counter()
    try:
        proc = subprocess.run(exec_cmd, capture_output=True, text=True, timeout=timeout)
        duration_ms = int((time.perf_counter() - t0) * 1000)
        passed = proc.returncode == 0
        LOGGER.info(
            "docker exec done  returncode=%d  passed=%s  duration_ms=%d",
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
        )
    except subprocess.TimeoutExpired:
        duration_ms = int((time.perf_counter() - t0) * 1000)
        LOGGER.warning("docker exec timed out  timeout=%ds", timeout)
        return PytestResult(
            ran=True,
            returncode=-1,
            passed=False,
            error=f"timed out after {timeout}s",
            duration_ms=duration_ms,
            docker_image=image,
        )
    except Exception as exc:
        duration_ms = int((time.perf_counter() - t0) * 1000)
        LOGGER.exception("docker exec failed unexpectedly")
        return PytestResult(ran=False, error=str(exc), duration_ms=duration_ms, docker_image=image)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _resolve_test_command_args(test_command: str) -> list[str]:
    """Return the test command argv exactly as configured in task YAML.

    Many images include `uv` but do not expose a global `pytest` binary on PATH.
    Preserving `uv run pytest ...` avoids false `pytest: not found` failures.
    """
    return shlex.split(test_command)


def _build_exec_command(*, container_name: str, test_args: list[str]) -> list[str]:
    """Build docker exec argv.

    For ``uv run pytest ...`` commands we prefer a local pytest binary when present
    to avoid networked uv environment resolution in network-isolated containers.
    """
    pytest_args = _extract_uv_pytest_args(test_args)
    if not pytest_args:
        return ["docker", "exec", container_name, *test_args]

    suffix = " ".join(shlex.quote(arg) for arg in pytest_args[1:])
    suffix = f" {suffix}" if suffix else ""
    shell_cmd = (
        f"if command -v pytest >/dev/null 2>&1; then "
        f"pytest{suffix}; "
        f"elif [ -x /opt/hybrid-example/.venv/bin/pytest ]; then "
        f"/opt/hybrid-example/.venv/bin/pytest{suffix}; "
        f"elif [ -x /opt/script30/.venv/bin/pytest ]; then "
        f"/opt/script30/.venv/bin/pytest{suffix}; "
        f"elif [ -x /workspace/.venv/bin/pytest ]; then "
        f"/workspace/.venv/bin/pytest{suffix}; "
        f"else "
        f"uv run pytest{suffix}; "
        f"fi"
    )
    return ["docker", "exec", container_name, "sh", "-lc", shell_cmd]


def _extract_uv_pytest_args(args: list[str]) -> list[str] | None:
    """Return ``pytest ...`` tail for uv-run invocations, else None."""
    if len(args) < 3 or args[0] != "uv" or args[1] != "run":
        return None
    i = 2
    while i < len(args) and args[i].startswith("-"):
        i += 1
    if i < len(args) and args[i] == "pytest":
        return args[i:]
    return None
