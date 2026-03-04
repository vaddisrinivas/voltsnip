"""Tests for vsevals.loader — suite YAML loading and path resolution."""

from __future__ import annotations

from pathlib import Path

import pytest

from vsevals.loader import (
    _apply_repo_root_default,
    _as_str,
    _file_tasks,
    _git_root,
    _inject_usecase_docker_config,
    _inline_tasks,
    _nonempty,
    _norm_path,
    _resolve_default_repo_root,
    load_suite,
)


# ---------------------------------------------------------------------------
# _as_str
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("val,expected", [
    ("hello", "hello"),
    ("  spaced  ", "spaced"),
    ("", None),
    ("   ", None),
    (None, None),
    (123, None),
])
def test_as_str(val, expected):
    assert _as_str(val) == expected


# ---------------------------------------------------------------------------
# _nonempty
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("val,expected", [
    ("hello", True),
    ("", False),
    (None, False),
    ("  ", False),
])
def test_nonempty(val, expected):
    assert _nonempty(val) == expected


# ---------------------------------------------------------------------------
# _inline_tasks
# ---------------------------------------------------------------------------


def test_inline_tasks_present():
    raw = {"tasks": [{"task": {"id": "t1"}}]}
    assert _inline_tasks(raw) == [{"task": {"id": "t1"}}]


def test_inline_tasks_missing():
    assert _inline_tasks({}) == []


def test_inline_tasks_invalid_type():
    with pytest.raises(ValueError, match="tasks must be a list"):
        _inline_tasks({"tasks": "not a list"})


# ---------------------------------------------------------------------------
# _git_root
# ---------------------------------------------------------------------------


def test_git_root_finds_repo(tmp_path):
    (tmp_path / ".git").mkdir()
    sub = tmp_path / "sub" / "deep"
    sub.mkdir(parents=True)
    assert _git_root(sub) == tmp_path


def test_git_root_none(tmp_path):
    # tmp_path likely has no .git
    result = _git_root(tmp_path / "nonexistent")
    # May or may not find .git depending on host; just check it doesn't crash


# ---------------------------------------------------------------------------
# load_suite — full integration
# ---------------------------------------------------------------------------


def test_load_suite_inline(tmp_path):
    suite_yaml = tmp_path / "suite.yaml"
    suite_yaml.write_text("""
suite:
  version: "1.0"
  description: "test suite"

models:
  - openai:gpt-5-mini

variants:
  - id: P0
    mode: direct
    memory_enabled: false
    tools_enabled: false
    retrieval_mode: none
    instruction_mode: none
    context_surface: user

tasks:
  - task:
      id: BUG01
      name: Test Bug
      user_prompt: Fix the bug
""")
    suite = load_suite(suite_yaml)
    assert suite.suite.version == "1.0"
    assert len(suite.tasks) == 1
    assert suite.tasks[0].task.id == "BUG01"
    assert len(suite.variants) == 1
    assert suite.model_names == ["openai:gpt-5-mini"]


def test_load_suite_with_task_files(tmp_path):
    tasks_yaml = tmp_path / "tasks.yaml"
    tasks_yaml.write_text("""
tasks:
  - task:
      id: BUG02
      name: External Bug
      user_prompt: Fix external bug
""")
    suite_yaml = tmp_path / "suite.yaml"
    suite_yaml.write_text(f"""
suite:
  version: "1.0"

models:
  - openai:gpt-5-mini

variants:
  - id: P0
    mode: direct
    memory_enabled: false
    tools_enabled: false
    retrieval_mode: none
    instruction_mode: none
    context_surface: user

task_files:
  - tasks.yaml
""")
    suite = load_suite(suite_yaml)
    assert len(suite.tasks) == 1
    assert suite.tasks[0].task.id == "BUG02"


def test_load_suite_with_default_repo_root(tmp_path):
    suite_yaml = tmp_path / "suite.yaml"
    suite_yaml.write_text(f"""
suite:
  version: "1.0"
  default_repo_root: /tmp/test_repo

models:
  - openai:gpt-5-mini

variants:
  - id: P0
    mode: direct
    memory_enabled: false
    tools_enabled: false
    retrieval_mode: none
    instruction_mode: none
    context_surface: user

tasks:
  - task:
      id: BUG01
      name: Test
      user_prompt: Fix
""")
    suite = load_suite(suite_yaml)
    # On macOS /tmp resolves to /private/tmp
    assert suite.tasks[0].task.repo_root.endswith("/tmp/test_repo")


def test_load_suite_invalid_yaml(tmp_path):
    suite_yaml = tmp_path / "suite.yaml"
    suite_yaml.write_text("just a string")
    with pytest.raises(ValueError, match="must be a mapping"):
        load_suite(suite_yaml)


def test_load_suite_missing_file():
    with pytest.raises(Exception):
        load_suite("/nonexistent/path/suite.yaml")


def test_load_suite_task_files_list_format(tmp_path):
    """Test task_files with list-format YAML (not mapping)."""
    tasks_yaml = tmp_path / "tasks_list.yaml"
    tasks_yaml.write_text("""
- task:
    id: BUG03
    name: List Bug
    user_prompt: Fix it
""")
    suite_yaml = tmp_path / "suite.yaml"
    suite_yaml.write_text(f"""
suite:
  version: "1.0"

models:
  - openai:gpt-5-mini

variants:
  - id: P0
    mode: direct
    memory_enabled: false
    tools_enabled: false
    retrieval_mode: none
    instruction_mode: none
    context_surface: user

task_files:
  - tasks_list.yaml
""")
    suite = load_suite(suite_yaml)
    assert suite.tasks[0].task.id == "BUG03"


def test_load_suite_with_usecase_manifest(tmp_path):
    usecase_yaml = tmp_path / "usecase.yaml"
    usecase_yaml.write_text("""
usecase:
  pytest_docker_image: test-image:latest
  pytest_docker_workdir: /workspace
""")
    suite_yaml = tmp_path / "suite.yaml"
    suite_yaml.write_text(f"""
suite:
  version: "1.0"
  usecase_manifest: usecase.yaml

models:
  - openai:gpt-5-mini

variants:
  - id: P0
    mode: direct
    memory_enabled: false
    tools_enabled: false
    retrieval_mode: none
    instruction_mode: none
    context_surface: user

tasks:
  - task:
      id: BUG01
      name: Test
      user_prompt: Fix
""")
    suite = load_suite(suite_yaml)
    assert suite.suite.pytest_docker_image == "test-image:latest"
    assert suite.suite.pytest_docker_workdir == "/workspace"


# ---------------------------------------------------------------------------
# _file_tasks — edge cases
# ---------------------------------------------------------------------------


def test_file_tasks_invalid_type(tmp_path):
    """task_files not a list raises ValueError."""
    suite_path = tmp_path / "suite.yaml"
    suite_path.write_text("dummy: true")
    raw = {"task_files": "not-a-list"}
    with pytest.raises(ValueError, match="task_files must be a list"):
        _file_tasks(raw, suite_path)


def test_file_tasks_empty_entry(tmp_path):
    """Empty string entry raises ValueError."""
    suite_path = tmp_path / "suite.yaml"
    suite_path.write_text("dummy: true")
    raw = {"task_files": [""]}
    with pytest.raises(ValueError, match="non-empty strings"):
        _file_tasks(raw, suite_path)


def test_file_tasks_invalid_file_format(tmp_path):
    """Task file that is neither list nor mapping raises ValueError."""
    bad_yaml = tmp_path / "bad_tasks.yaml"
    bad_yaml.write_text("just a string")
    suite_path = tmp_path / "suite.yaml"
    suite_path.write_text("dummy: true")
    raw = {"task_files": ["bad_tasks.yaml"]}
    with pytest.raises(ValueError, match="must be list or mapping"):
        _file_tasks(raw, suite_path)


def test_file_tasks_mapping_without_tasks_key(tmp_path):
    """Mapping missing 'tasks' key raises ValueError."""
    bad_yaml = tmp_path / "bad_tasks.yaml"
    bad_yaml.write_text("other_key:\n  - stuff")
    suite_path = tmp_path / "suite.yaml"
    suite_path.write_text("dummy: true")
    raw = {"task_files": ["bad_tasks.yaml"]}
    with pytest.raises(ValueError, match="must contain list 'tasks'"):
        _file_tasks(raw, suite_path)


# ---------------------------------------------------------------------------
# _apply_repo_root_default — edge cases
# ---------------------------------------------------------------------------


def test_apply_repo_root_default_no_suite_meta(tmp_path):
    """Returns tasks unchanged when no suite meta."""
    suite_path = tmp_path / "suite.yaml"
    suite_path.write_text("dummy: true")
    tasks = [{"task": {"id": "t1"}}]
    result = _apply_repo_root_default({}, suite_path, tasks)
    assert result == tasks


def test_apply_repo_root_default_with_existing_repo_root(tmp_path):
    """Doesn't override tasks that already have repo_root."""
    suite_path = tmp_path / "suite.yaml"
    suite_path.write_text("dummy: true")
    raw = {"suite": {"default_repo_root": "/default/root"}}
    tasks = [{"task": {"id": "t1", "repo_root": "/existing/root"}}]
    result = _apply_repo_root_default(raw, suite_path, tasks)
    assert result[0]["task"]["repo_root"] == "/existing/root"


# ---------------------------------------------------------------------------
# _norm_path — edge cases
# ---------------------------------------------------------------------------


def test_norm_path_absolute(tmp_path):
    """Absolute path returned as resolved."""
    suite_path = tmp_path / "suite.yaml"
    suite_path.write_text("dummy: true")
    result = _norm_path("/tmp/absolute/path", suite_path, tmp_path)
    assert result.endswith("/tmp/absolute/path")


def test_norm_path_relative_from_base_exists(tmp_path):
    """Resolves relative from base when dir exists."""
    sub = tmp_path / "sub"
    sub.mkdir()
    suite_path = tmp_path / "suite.yaml"
    suite_path.write_text("dummy: true")
    result = _norm_path("sub", suite_path, tmp_path)
    assert result == str(sub.resolve())


def test_norm_path_relative_falls_to_git_root(tmp_path):
    """Falls to git root when base doesn't resolve to existing path."""
    # Create a git root marker
    (tmp_path / ".git").mkdir()
    deeper = tmp_path / "deep" / "nested"
    deeper.mkdir(parents=True)
    suite_path = deeper / "suite.yaml"
    suite_path.write_text("dummy: true")
    # "some_dir" doesn't exist in deeper/ but should fall back to git root
    result = _norm_path("some_dir", suite_path, deeper)
    assert result == str((tmp_path / "some_dir").resolve())


# ---------------------------------------------------------------------------
# _inject_usecase_docker_config — edge cases
# ---------------------------------------------------------------------------


def test_inject_usecase_docker_no_suite_meta(tmp_path):
    """Returns early if no suite meta."""
    raw = {}
    suite_path = tmp_path / "suite.yaml"
    suite_path.write_text("dummy: true")
    _inject_usecase_docker_config(raw, suite_path)
    assert "suite" not in raw


def test_inject_usecase_docker_no_manifest(tmp_path):
    """Returns early if no usecase_manifest."""
    raw = {"suite": {"version": "1.0"}}
    suite_path = tmp_path / "suite.yaml"
    suite_path.write_text("dummy: true")
    _inject_usecase_docker_config(raw, suite_path)
    assert "pytest_docker_image" not in raw["suite"]


def test_inject_usecase_docker_already_set(tmp_path):
    """Doesn't override existing values."""
    usecase_yaml = tmp_path / "usecase.yaml"
    usecase_yaml.write_text("""
usecase:
  pytest_docker_image: new-image:v2
  pytest_docker_workdir: /new
""")
    suite_path = tmp_path / "suite.yaml"
    suite_path.write_text("dummy: true")
    raw = {
        "suite": {
            "usecase_manifest": "usecase.yaml",
            "pytest_docker_image": "existing-image:v1",
            "pytest_docker_workdir": "/existing",
        }
    }
    _inject_usecase_docker_config(raw, suite_path)
    assert raw["suite"]["pytest_docker_image"] == "existing-image:v1"
    assert raw["suite"]["pytest_docker_workdir"] == "/existing"


# ---------------------------------------------------------------------------
# load_suite — usecase repo_root resolution
# ---------------------------------------------------------------------------


def test_load_suite_with_usecase_repo_root(tmp_path):
    """Usecase with repo_root resolves correctly."""
    repo_dir = tmp_path / "myrepo"
    repo_dir.mkdir()
    usecase_yaml = tmp_path / "usecase.yaml"
    usecase_yaml.write_text(f"""
usecase:
  repo_root: {str(repo_dir)}
""")
    suite_yaml = tmp_path / "suite.yaml"
    suite_yaml.write_text(f"""
suite:
  version: "1.0"
  usecase_manifest: usecase.yaml

models:
  - openai:gpt-5-mini

variants:
  - id: P0
    mode: direct
    memory_enabled: false
    tools_enabled: false
    retrieval_mode: none
    instruction_mode: none
    context_surface: user

tasks:
  - task:
      id: BUG01
      name: Test
      user_prompt: Fix
""")
    suite = load_suite(suite_yaml)
    assert suite.tasks[0].task.repo_root == str(repo_dir.resolve())


def test_load_suite_with_project_relative_root(tmp_path):
    """Usecase with project_relative_root resolves relative to suite dir."""
    rel_dir = tmp_path / "rel_root"
    rel_dir.mkdir()
    usecase_yaml = tmp_path / "usecase.yaml"
    usecase_yaml.write_text("""
usecase:
  project_relative_root: rel_root
""")
    suite_yaml = tmp_path / "suite.yaml"
    suite_yaml.write_text(f"""
suite:
  version: "1.0"
  usecase_manifest: usecase.yaml

models:
  - openai:gpt-5-mini

variants:
  - id: P0
    mode: direct
    memory_enabled: false
    tools_enabled: false
    retrieval_mode: none
    instruction_mode: none
    context_surface: user

tasks:
  - task:
      id: BUG01
      name: Test
      user_prompt: Fix
""")
    suite = load_suite(suite_yaml)
    assert suite.tasks[0].task.repo_root == str(rel_dir.resolve())


def test_resolve_default_repo_root_missing_manifest(tmp_path):
    """Raises ValueError when manifest file doesn't exist."""
    suite_path = tmp_path / "suite.yaml"
    suite_path.write_text("dummy: true")
    raw = {"suite": {"usecase_manifest": "nonexistent.yaml", "default_repo_root": None}}
    # _resolve_default_repo_root is called by _apply_repo_root_default.
    # When the manifest doesn't exist, it raises ValueError.
    with pytest.raises(ValueError, match="usecase_manifest not found"):
        _resolve_default_repo_root(raw, suite_path)
