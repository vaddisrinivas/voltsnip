"""Suite and task YAML loader.

Usage:
    suite = load_suite("path/to/suite.yaml")
    task   = suite.task_map["BUG01"]
    variant = suite.variant_map["P0"]
"""

from __future__ import annotations

from pathlib import Path

import yaml

from vsevals.models import SuiteConfig


def load_suite(path: str | Path) -> SuiteConfig:
    """Load and validate a suite YAML file.

    Supports both inline tasks and task_files references.
    Applies default_repo_root from suite metadata to tasks that don't set one.
    """
    suite_path = Path(path).expanduser().resolve()
    raw = yaml.safe_load(suite_path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError(f"suite YAML must be a mapping: {suite_path}")

    combined = _inline_tasks(raw) + _file_tasks(raw, suite_path)
    combined = _apply_repo_root_default(raw, suite_path, combined)
    raw["tasks"] = combined

    # Inject pytest docker config from usecase.yaml into suite meta
    _inject_usecase_docker_config(raw, suite_path)

    return SuiteConfig.model_validate(raw)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _inline_tasks(raw: dict) -> list:
    payload = raw.get("tasks")
    if payload is None:
        return []
    if not isinstance(payload, list):
        raise ValueError("tasks must be a list")
    return list(payload)


def _file_tasks(raw: dict, suite_path: Path) -> list:
    task_files = raw.get("task_files")
    if task_files is None:
        return []
    if not isinstance(task_files, list):
        raise ValueError("task_files must be a list")

    tasks: list = []
    for entry in task_files:
        if not isinstance(entry, str) or not entry.strip():
            raise ValueError("task_files entries must be non-empty strings")
        task_path = (suite_path.parent / entry).expanduser().resolve()
        payload = yaml.safe_load(task_path.read_text(encoding="utf-8"))
        if isinstance(payload, dict):
            if not isinstance(payload.get("tasks"), list):
                raise ValueError(f"task file mapping must contain list 'tasks': {task_path}")
            tasks.extend(payload["tasks"])
        elif isinstance(payload, list):
            tasks.extend(payload)
        else:
            raise ValueError(f"task file must be list or mapping: {task_path}")
    return tasks


def _apply_repo_root_default(raw: dict, suite_path: Path, tasks: list) -> list:
    """Inject default_repo_root into tasks that don't already set repo_root."""
    default_root = _resolve_default_repo_root(raw, suite_path)
    if default_root is None:
        return tasks

    result: list = []
    for item in tasks:
        if isinstance(item, dict) and isinstance(item.get("task"), dict):
            task = item["task"]
            if not _nonempty(task.get("repo_root")):
                task["repo_root"] = default_root
        result.append(item)
    return result


def _resolve_default_repo_root(raw: dict, suite_path: Path) -> str | None:
    suite_meta = raw.get("suite")
    if not isinstance(suite_meta, dict):
        return None

    direct = _as_str(suite_meta.get("default_repo_root"))
    if direct:
        return _norm_path(direct, suite_path, suite_path.parent)

    manifest_val = _as_str(suite_meta.get("usecase_manifest"))
    if not manifest_val:
        return None

    manifest_path = (suite_path.parent / manifest_val).expanduser().resolve()
    if not manifest_path.exists():
        raise ValueError(f"usecase_manifest not found: {manifest_path}")
    payload = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        return None

    usecase = payload.get("usecase")
    if isinstance(usecase, dict):
        repo_root = _as_str(usecase.get("repo_root"))
        if repo_root:
            return _norm_path(repo_root, suite_path, manifest_path.parent)
        project_rel = _as_str(usecase.get("project_relative_root"))
        if project_rel:
            return _norm_path(project_rel, suite_path, suite_path.parent)
    return None


def _norm_path(raw: str, suite_path: Path, base: Path) -> str:
    candidate = Path(raw).expanduser()
    if candidate.is_absolute():
        return str(candidate.resolve())
    from_base = (base / candidate).resolve()
    if from_base.exists():
        return str(from_base)
    git_root = _git_root(suite_path.parent)
    if git_root:
        return str((git_root / candidate).resolve())
    return str(from_base)


def _git_root(start: Path) -> Path | None:
    for p in (start, *start.parents):
        if (p / ".git").exists():
            return p
    return None


def _inject_usecase_docker_config(raw: dict, suite_path: Path) -> None:
    """Read pytest_docker_image and pytest_docker_workdir from usecase.yaml.

    Writes them into raw["suite"] so SuiteMeta carries them.
    Only fills in fields not already present in raw["suite"].
    """
    suite_meta = raw.get("suite")
    if not isinstance(suite_meta, dict):
        return
    manifest_val = _as_str(suite_meta.get("usecase_manifest"))
    if not manifest_val:
        return
    manifest_path = (suite_path.parent / manifest_val).expanduser().resolve()
    if not manifest_path.exists():
        return
    payload = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        return
    usecase = payload.get("usecase")
    if not isinstance(usecase, dict):
        return
    for key in ("pytest_docker_image", "pytest_docker_workdir"):
        val = _as_str(usecase.get(key))
        if val and suite_meta.get(key) is None:
            suite_meta[key] = val


def _as_str(v: object) -> str | None:
    if isinstance(v, str) and v.strip():
        return v.strip()
    return None


def _nonempty(v: object) -> bool:
    return _as_str(v) is not None
