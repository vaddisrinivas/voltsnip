"""Docker primitives for pytest execution — thin layer over Docker CLI."""

from __future__ import annotations

import logging
import shlex
import subprocess
import time
import uuid
from pathlib import Path

from vsevals.models import PytestResult, RunConfig

LOGGER = logging.getLogger(__name__)


def start_test_container(*, image: str, workdir: str, timeout_seconds: int,
                         host_workdir: str | None = None) -> str:
    name = f"moltsnip-pytest-{uuid.uuid4().hex[:12]}"
    cmd = ["docker", "run", "-d", "--name", name, "--workdir", workdir, "--network", "none"]
    if host_workdir:
        cmd.extend(["-v", f"{host_workdir}:{workdir}"])
    try:
        uv_cache = subprocess.run(
            ["uv", "cache", "dir"], capture_output=True, text=True, check=True,
        ).stdout.strip()
        if uv_cache and Path(uv_cache).is_dir():
            cmd.extend(["-v", f"{uv_cache}:{uv_cache}", "-e", f"UV_CACHE_DIR={uv_cache}"])
            LOGGER.debug("mounting uv cache  host=%s", uv_cache)
    except Exception:
        pass
    cmd.extend([image, "sleep", str(timeout_seconds + 60)])
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"docker run failed: {result.stderr.strip()}")
    LOGGER.debug("container started  name=%s  image=%s  host_workdir=%s", name, image, host_workdir)
    return name


def stop_test_container(container_name: str) -> None:
    subprocess.run(["docker", "rm", "-f", container_name], capture_output=True, check=False)
    LOGGER.debug("container removed  name=%s", container_name)


def docker_cp(src_host: Path, container_name: str, container_path: str) -> None:
    parent = str(Path(container_path).parent)
    mkdir_result = subprocess.run(
        ["docker", "exec", container_name, "mkdir", "-p", parent], capture_output=True, text=True,
    )
    if mkdir_result.returncode != 0:
        raise RuntimeError(f"docker exec mkdir -p {parent} in {container_name} failed: {mkdir_result.stderr.strip()}")
    result = subprocess.run(
        ["docker", "cp", str(src_host.resolve()), f"{container_name}:{container_path}"],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"docker cp {src_host} → {container_name}:{container_path} failed: {result.stderr.strip()}")
    LOGGER.debug("docker cp  src=%s  dst=%s:%s", src_host, container_name, container_path)


def run_pytest_in_docker(*, container_name: str, test_command: str, cfg: RunConfig) -> PytestResult:
    image = cfg.pytest_docker_image
    timeout = cfg.pytest_timeout_seconds
    exec_cmd = _build_exec_command(container_name=container_name, test_args=shlex.split(test_command))
    LOGGER.info("docker exec  container=%s  cmd=%s", container_name, " ".join(exec_cmd[2:]))
    t0 = time.perf_counter()
    try:
        proc = subprocess.run(exec_cmd, capture_output=True, text=True, timeout=timeout)
        duration_ms = int((time.perf_counter() - t0) * 1000)
        passed = proc.returncode == 0
        LOGGER.info("docker exec done  returncode=%d  passed=%s  duration_ms=%d", proc.returncode, passed, duration_ms)
        return PytestResult(
            ran=True, returncode=proc.returncode, passed=passed,
            stdout=proc.stdout[:8192], stderr=proc.stderr[:4096],
            duration_ms=duration_ms, docker_image=image,
        )
    except subprocess.TimeoutExpired:
        duration_ms = int((time.perf_counter() - t0) * 1000)
        LOGGER.warning("docker exec timed out  timeout=%ds", timeout)
        return PytestResult(ran=True, returncode=-1, passed=False,
                            error=f"timed out after {timeout}s", duration_ms=duration_ms, docker_image=image)
    except Exception as exc:
        duration_ms = int((time.perf_counter() - t0) * 1000)
        LOGGER.exception("docker exec failed unexpectedly")
        return PytestResult(ran=False, error=str(exc), duration_ms=duration_ms, docker_image=image)


def _build_exec_command(*, container_name: str, test_args: list[str]) -> list[str]:
    pytest_args = _extract_uv_pytest_args(test_args)
    if not pytest_args:
        return ["docker", "exec", container_name, *test_args]
    suffix = (" " + " ".join(shlex.quote(arg) for arg in pytest_args[1:])).rstrip()
    shell_cmd = (
        f"if command -v pytest >/dev/null 2>&1; then pytest{suffix}; "
        f"elif [ -x /opt/hybrid-example/.venv/bin/pytest ]; then /opt/hybrid-example/.venv/bin/pytest{suffix}; "
        f"elif [ -x /opt/script30/.venv/bin/pytest ]; then /opt/script30/.venv/bin/pytest{suffix}; "
        f"elif [ -x /workspace/.venv/bin/pytest ]; then /workspace/.venv/bin/pytest{suffix}; "
        f"else uv run pytest{suffix}; fi"
    )
    return ["docker", "exec", container_name, "sh", "-lc", shell_cmd]


def _extract_uv_pytest_args(args: list[str]) -> list[str] | None:
    if len(args) < 3 or args[0] != "uv" or args[1] != "run":
        return None
    i = 2
    while i < len(args) and args[i].startswith("-"):
        i += 1
    return args[i:] if i < len(args) and args[i] == "pytest" else None
