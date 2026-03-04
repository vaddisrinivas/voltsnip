"""Tests for vsevals.pytest_runner — Docker-based pytest execution primitives."""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import MagicMock, call, patch

import pytest

from vsevals.models import PytestResult, RunConfig
from vsevals.pytest_runner import (
    _build_exec_command,
    _extract_uv_pytest_args,
    _resolve_test_command_args,
    docker_cp,
    run_pytest_in_docker,
    start_test_container,
    stop_test_container,
)


# ---------------------------------------------------------------------------
# _extract_uv_pytest_args
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "args, expected",
    [
        # Basic uv run pytest invocation
        (["uv", "run", "pytest"], ["pytest"]),
        # With trailing flags and paths
        (["uv", "run", "pytest", "-v", "tests/"], ["pytest", "-v", "tests/"]),
        # With uv flags before pytest (--no-sync etc.)
        (["uv", "run", "--no-sync", "pytest", "-v"], ["pytest", "-v"]),
        # Multiple uv flags before pytest
        (
            ["uv", "run", "--no-sync", "--frozen", "pytest", "-x"],
            ["pytest", "-x"],
        ),
        # Not a uv invocation — starts with pytest
        (["pytest", "-v"], None),
        # uv run with a different tool (not pytest)
        (["uv", "run", "mypy"], None),
        # Empty list
        ([], None),
        # uv run with no further args (no pytest)
        (["uv", "run"], None),
        # Too short (only "uv")
        (["uv"], None),
        # uv run with only flags, no pytest
        (["uv", "run", "--no-sync"], None),
        # First element is not "uv"
        (["pip", "run", "pytest"], None),
    ],
    ids=[
        "basic_uv_pytest",
        "uv_pytest_with_flags",
        "uv_no_sync_pytest",
        "multiple_uv_flags",
        "bare_pytest",
        "uv_run_mypy",
        "empty_list",
        "uv_run_no_tool",
        "only_uv",
        "uv_run_only_flags",
        "pip_run_pytest",
    ],
)
def test_extract_uv_pytest_args(args, expected):
    assert _extract_uv_pytest_args(args) == expected


# ---------------------------------------------------------------------------
# _resolve_test_command_args
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "command, expected",
    [
        ("pytest tests/", ["pytest", "tests/"]),
        ("uv run pytest -v", ["uv", "run", "pytest", "-v"]),
        ("pytest -x --tb=short tests/unit/", ["pytest", "-x", "--tb=short", "tests/unit/"]),
        ("uv run --no-sync pytest -v tests/", ["uv", "run", "--no-sync", "pytest", "-v", "tests/"]),
    ],
    ids=[
        "simple_pytest",
        "uv_run_pytest",
        "pytest_multiple_flags",
        "uv_with_flags_and_path",
    ],
)
def test_resolve_test_command_args(command, expected):
    assert _resolve_test_command_args(command) == expected


# ---------------------------------------------------------------------------
# _build_exec_command — non-uv path
# ---------------------------------------------------------------------------


def test_build_exec_command_non_uv():
    result = _build_exec_command(
        container_name="ctr-abc",
        test_args=["pytest", "-v", "tests/"],
    )
    assert result == ["docker", "exec", "ctr-abc", "pytest", "-v", "tests/"]


def test_build_exec_command_non_uv_single_arg():
    result = _build_exec_command(
        container_name="ctr-xyz",
        test_args=["pytest"],
    )
    assert result == ["docker", "exec", "ctr-xyz", "pytest"]


# ---------------------------------------------------------------------------
# _build_exec_command — uv path (shell fallback chain)
# ---------------------------------------------------------------------------


def test_build_exec_command_uv_basic():
    result = _build_exec_command(
        container_name="ctr-abc",
        test_args=["uv", "run", "pytest"],
    )
    # Should produce: docker exec <name> sh -lc <shell_cmd>
    assert result[0:3] == ["docker", "exec", "ctr-abc"]
    assert result[3] == "sh"
    assert result[4] == "-lc"
    shell_cmd = result[5]
    # The shell script should contain the fallback chain
    assert "command -v pytest" in shell_cmd
    assert "uv run pytest" in shell_cmd


def test_build_exec_command_uv_with_args():
    result = _build_exec_command(
        container_name="ctr-abc",
        test_args=["uv", "run", "pytest", "-v", "tests/"],
    )
    shell_cmd = result[5]
    # Suffix args should appear after each pytest path in the fallback
    assert "-v" in shell_cmd
    assert "tests/" in shell_cmd
    # The fallback should end with uv run pytest plus args
    assert "uv run pytest" in shell_cmd


def test_build_exec_command_uv_with_flags():
    result = _build_exec_command(
        container_name="ctr-abc",
        test_args=["uv", "run", "--no-sync", "pytest", "-x"],
    )
    shell_cmd = result[5]
    assert "pytest" in shell_cmd
    assert "-x" in shell_cmd


# ---------------------------------------------------------------------------
# start_test_container
# ---------------------------------------------------------------------------


@patch("vsevals.pytest_runner.subprocess.run")
@patch("vsevals.pytest_runner.uuid")
def test_start_test_container_success(mock_uuid, mock_run):
    mock_uuid.uuid4.return_value = MagicMock(hex="aabbccddeeff1122")
    # First call: uv cache dir (fails so we skip that branch)
    # Second call: docker run (succeeds)
    mock_run.side_effect = [
        subprocess.CalledProcessError(1, "uv"),  # uv cache dir fails
        MagicMock(returncode=0, stderr=""),        # docker run succeeds
    ]

    name = start_test_container(
        image="python:3.12",
        workdir="/workspace",
        timeout_seconds=120,
    )

    assert name == "moltsnip-pytest-aabbccddeeff"
    # Docker run call should include sleep <timeout+60>
    docker_run_call = mock_run.call_args_list[1]
    cmd = docker_run_call[0][0]
    assert "docker" in cmd
    assert "run" in cmd
    assert "sleep" in cmd
    assert "180" in cmd  # 120 + 60
    assert "--network" in cmd
    assert "none" in cmd


@patch("vsevals.pytest_runner.subprocess.run")
@patch("vsevals.pytest_runner.uuid")
def test_start_test_container_with_host_workdir(mock_uuid, mock_run):
    mock_uuid.uuid4.return_value = MagicMock(hex="aabbccddeeff1122")
    mock_run.side_effect = [
        subprocess.CalledProcessError(1, "uv"),  # uv cache dir fails
        MagicMock(returncode=0, stderr=""),
    ]

    start_test_container(
        image="python:3.12",
        workdir="/workspace",
        timeout_seconds=60,
        host_workdir="/home/user/project",
    )

    docker_run_call = mock_run.call_args_list[1]
    cmd = docker_run_call[0][0]
    assert "-v" in cmd
    idx = cmd.index("-v")
    assert cmd[idx + 1] == "/home/user/project:/workspace"


@patch("vsevals.pytest_runner.Path")
@patch("vsevals.pytest_runner.subprocess.run")
@patch("vsevals.pytest_runner.uuid")
def test_start_test_container_with_uv_cache(mock_uuid, mock_run, mock_path_cls):
    mock_uuid.uuid4.return_value = MagicMock(hex="aabbccddeeff1122")
    # uv cache dir succeeds, returns a valid path
    uv_cache_result = MagicMock(stdout="/home/user/.cache/uv\n", returncode=0)
    mock_run.side_effect = [
        uv_cache_result,                            # uv cache dir
        MagicMock(returncode=0, stderr=""),          # docker run
    ]
    # Path(uv_cache).is_dir() returns True
    mock_path_instance = MagicMock()
    mock_path_instance.is_dir.return_value = True
    mock_path_cls.return_value = mock_path_instance

    start_test_container(
        image="python:3.12",
        workdir="/workspace",
        timeout_seconds=60,
    )

    docker_run_call = mock_run.call_args_list[1]
    cmd = docker_run_call[0][0]
    # Should have the uv cache volume mount
    assert "-v" in cmd
    # Find all -v flags
    volume_mounts = [cmd[i + 1] for i, v in enumerate(cmd) if v == "-v"]
    uv_mount = "/home/user/.cache/uv:/home/user/.cache/uv"
    assert uv_mount in volume_mounts
    # Should also set the UV_CACHE_DIR env var
    assert "-e" in cmd
    env_idx = cmd.index("-e")
    assert cmd[env_idx + 1] == "UV_CACHE_DIR=/home/user/.cache/uv"


@patch("vsevals.pytest_runner.subprocess.run")
@patch("vsevals.pytest_runner.uuid")
def test_start_test_container_docker_run_fails(mock_uuid, mock_run):
    mock_uuid.uuid4.return_value = MagicMock(hex="aabbccddeeff1122")
    mock_run.side_effect = [
        subprocess.CalledProcessError(1, "uv"),       # uv cache dir fails
        MagicMock(returncode=1, stderr="no such image"),  # docker run fails
    ]

    with pytest.raises(RuntimeError, match="docker run failed"):
        start_test_container(
            image="nonexistent:latest",
            workdir="/workspace",
            timeout_seconds=60,
        )


@patch("vsevals.pytest_runner.Path")
@patch("vsevals.pytest_runner.subprocess.run")
@patch("vsevals.pytest_runner.uuid")
def test_start_test_container_uv_cache_dir_not_directory(mock_uuid, mock_run, mock_path_cls):
    """uv cache dir returns a path that is not actually a directory -- skip silently."""
    mock_uuid.uuid4.return_value = MagicMock(hex="aabbccddeeff1122")
    uv_cache_result = MagicMock(stdout="/nonexistent/path\n", returncode=0)
    mock_run.side_effect = [
        uv_cache_result,
        MagicMock(returncode=0, stderr=""),
    ]
    mock_path_instance = MagicMock()
    mock_path_instance.is_dir.return_value = False
    mock_path_cls.return_value = mock_path_instance

    name = start_test_container(
        image="python:3.12",
        workdir="/workspace",
        timeout_seconds=60,
    )

    # Should still succeed but NOT have the uv cache volume mount
    assert name.startswith("moltsnip-pytest-")
    docker_run_call = mock_run.call_args_list[1]
    cmd = docker_run_call[0][0]
    # No UV_CACHE_DIR should be present
    assert "UV_CACHE_DIR=/nonexistent/path" not in " ".join(cmd)


# ---------------------------------------------------------------------------
# stop_test_container
# ---------------------------------------------------------------------------


@patch("vsevals.pytest_runner.subprocess.run")
def test_stop_test_container(mock_run):
    stop_test_container("ctr-abc123")

    mock_run.assert_called_once_with(
        ["docker", "rm", "-f", "ctr-abc123"],
        capture_output=True,
        check=False,
    )


# ---------------------------------------------------------------------------
# docker_cp
# ---------------------------------------------------------------------------


@patch("vsevals.pytest_runner.subprocess.run")
def test_docker_cp_success(mock_run):
    mock_run.side_effect = [
        MagicMock(returncode=0),  # mkdir
        MagicMock(returncode=0),  # cp
    ]

    docker_cp(
        src_host=Path("/tmp/patched.py"),
        container_name="ctr-abc",
        container_path="/workspace/src/main.py",
    )

    assert mock_run.call_count == 2
    # First call: mkdir -p for parent dir
    mkdir_call = mock_run.call_args_list[0]
    mkdir_cmd = mkdir_call[0][0]
    assert mkdir_cmd == ["docker", "exec", "ctr-abc", "mkdir", "-p", "/workspace/src"]
    # Second call: docker cp
    cp_call = mock_run.call_args_list[1]
    cp_cmd = cp_call[0][0]
    assert cp_cmd[0:2] == ["docker", "cp"]
    assert "ctr-abc:/workspace/src/main.py" in cp_cmd


@patch("vsevals.pytest_runner.subprocess.run")
def test_docker_cp_mkdir_failure(mock_run):
    mock_run.return_value = MagicMock(returncode=1, stderr="permission denied")

    with pytest.raises(RuntimeError, match="docker exec mkdir"):
        docker_cp(
            src_host=Path("/tmp/patched.py"),
            container_name="ctr-abc",
            container_path="/workspace/src/main.py",
        )


@patch("vsevals.pytest_runner.subprocess.run")
def test_docker_cp_cp_failure(mock_run):
    mock_run.side_effect = [
        MagicMock(returncode=0),                        # mkdir succeeds
        MagicMock(returncode=1, stderr="no such file"),  # cp fails
    ]

    with pytest.raises(RuntimeError, match="docker cp"):
        docker_cp(
            src_host=Path("/tmp/patched.py"),
            container_name="ctr-abc",
            container_path="/workspace/src/main.py",
        )


# ---------------------------------------------------------------------------
# run_pytest_in_docker
# ---------------------------------------------------------------------------


def _make_cfg(**overrides) -> RunConfig:
    """Build a minimal RunConfig for testing."""
    defaults = dict(
        pytest_docker_image="moltsnip-pytest:latest",
        pytest_timeout_seconds=300,
    )
    defaults.update(overrides)
    return RunConfig(**defaults)


@patch("vsevals.pytest_runner.subprocess.run")
def test_run_pytest_pass(mock_run):
    mock_run.return_value = MagicMock(
        returncode=0,
        stdout="1 passed",
        stderr="",
    )
    cfg = _make_cfg()

    result = run_pytest_in_docker(
        container_name="ctr-abc",
        test_command="pytest tests/",
        cfg=cfg,
    )

    assert isinstance(result, PytestResult)
    assert result.ran is True
    assert result.passed is True
    assert result.returncode == 0
    assert result.stdout == "1 passed"
    assert result.docker_image == "moltsnip-pytest:latest"
    assert result.duration_ms is not None and result.duration_ms >= 0


@patch("vsevals.pytest_runner.subprocess.run")
def test_run_pytest_fail(mock_run):
    mock_run.return_value = MagicMock(
        returncode=1,
        stdout="1 failed",
        stderr="FAILED test_foo",
    )
    cfg = _make_cfg()

    result = run_pytest_in_docker(
        container_name="ctr-abc",
        test_command="pytest tests/",
        cfg=cfg,
    )

    assert result.ran is True
    assert result.passed is False
    assert result.returncode == 1
    assert "1 failed" in result.stdout


@patch("vsevals.pytest_runner.subprocess.run")
def test_run_pytest_timeout(mock_run):
    mock_run.side_effect = subprocess.TimeoutExpired(cmd="docker exec ...", timeout=300)
    cfg = _make_cfg(pytest_timeout_seconds=300)

    result = run_pytest_in_docker(
        container_name="ctr-abc",
        test_command="pytest tests/",
        cfg=cfg,
    )

    assert result.ran is True
    assert result.passed is False
    assert result.returncode == -1
    assert "timed out after 300s" in result.error
    assert result.docker_image == "moltsnip-pytest:latest"


@patch("vsevals.pytest_runner.subprocess.run")
def test_run_pytest_unexpected_exception(mock_run):
    mock_run.side_effect = OSError("Docker daemon not running")
    cfg = _make_cfg()

    result = run_pytest_in_docker(
        container_name="ctr-abc",
        test_command="pytest tests/",
        cfg=cfg,
    )

    assert result.ran is False
    assert result.error == "Docker daemon not running"
    assert result.docker_image == "moltsnip-pytest:latest"


@patch("vsevals.pytest_runner.subprocess.run")
def test_run_pytest_stdout_truncated(mock_run):
    """Stdout is capped at 8192 chars."""
    long_output = "x" * 20000
    mock_run.return_value = MagicMock(
        returncode=0,
        stdout=long_output,
        stderr="",
    )
    cfg = _make_cfg()

    result = run_pytest_in_docker(
        container_name="ctr-abc",
        test_command="pytest tests/",
        cfg=cfg,
    )

    assert len(result.stdout) == 8192


@patch("vsevals.pytest_runner.subprocess.run")
def test_run_pytest_stderr_truncated(mock_run):
    """Stderr is capped at 4096 chars."""
    long_err = "e" * 10000
    mock_run.return_value = MagicMock(
        returncode=1,
        stdout="",
        stderr=long_err,
    )
    cfg = _make_cfg()

    result = run_pytest_in_docker(
        container_name="ctr-abc",
        test_command="pytest tests/",
        cfg=cfg,
    )

    assert len(result.stderr) == 4096


@patch("vsevals.pytest_runner.subprocess.run")
def test_run_pytest_uses_cfg_timeout(mock_run):
    """The timeout kwarg passed to subprocess.run should match cfg.pytest_timeout_seconds."""
    mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
    cfg = _make_cfg(pytest_timeout_seconds=42)

    run_pytest_in_docker(
        container_name="ctr-abc",
        test_command="pytest tests/",
        cfg=cfg,
    )

    # subprocess.run should have been called with timeout=42
    _, kwargs = mock_run.call_args
    assert kwargs["timeout"] == 42


@patch("vsevals.pytest_runner.subprocess.run")
def test_run_pytest_uv_command_builds_shell(mock_run):
    """When test_command uses uv run pytest, the exec command should use sh -lc."""
    mock_run.return_value = MagicMock(returncode=0, stdout="ok", stderr="")
    cfg = _make_cfg()

    run_pytest_in_docker(
        container_name="ctr-abc",
        test_command="uv run pytest -v",
        cfg=cfg,
    )

    exec_cmd = mock_run.call_args[0][0]
    assert exec_cmd[3] == "sh"
    assert exec_cmd[4] == "-lc"


@patch("vsevals.pytest_runner.subprocess.run")
def test_run_pytest_nonzero_exit_not_one(mock_run):
    """Exit codes other than 0 should also be reported as not passed."""
    mock_run.return_value = MagicMock(
        returncode=2,  # pytest internal error
        stdout="",
        stderr="internal error",
    )
    cfg = _make_cfg()

    result = run_pytest_in_docker(
        container_name="ctr-abc",
        test_command="pytest tests/",
        cfg=cfg,
    )

    assert result.ran is True
    assert result.passed is False
    assert result.returncode == 2


# ---------------------------------------------------------------------------
# Integration-style: start + run + stop flow assertions
# ---------------------------------------------------------------------------


@patch("vsevals.pytest_runner.subprocess.run")
@patch("vsevals.pytest_runner.uuid")
def test_container_name_format(mock_uuid, mock_run):
    """Container name should follow moltsnip-pytest-<12hex> pattern."""
    mock_uuid.uuid4.return_value = MagicMock(hex="0123456789abcdef01234567")
    mock_run.side_effect = [
        subprocess.CalledProcessError(1, "uv"),
        MagicMock(returncode=0, stderr=""),
    ]

    name = start_test_container(
        image="python:3.12",
        workdir="/workspace",
        timeout_seconds=60,
    )

    assert name == "moltsnip-pytest-0123456789ab"
    assert len(name.split("-")[-1]) == 12
