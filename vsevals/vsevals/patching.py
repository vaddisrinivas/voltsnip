"""Isolated overlay patching for pytest runs.

Strategy: copy repo to overlay dir, write LLM code to target file, run pytest
in Docker mounting the overlay. Original repo is never modified.

Public API:
  materialize_overlay(repo_root, overlay_root)  — copy repo into overlay_root
  apply_rewrite(code, target_file, ...)          — write code into overlay
  cleanup_overlay(overlay_root)                  — remove overlay tree
"""

from __future__ import annotations

import logging
import shutil
from pathlib import Path

LOGGER = logging.getLogger(__name__)

_SKIP_DIRS = frozenset({
    ".git", ".venv", "venv", ".tox", "node_modules", "__pycache__",
    ".mypy_cache", ".ruff_cache", ".pytest_cache", "dist", "build",
    ".eggs", "*.egg-info", "htmlcov", ".coverage",
})
_SKIP_DIR_PREFIXES = (".", "__pycache__")


def _ignore_patterns(src: str, names: list[str]) -> set[str]:
    ignored: set[str] = set()
    for name in names:
        if name in _SKIP_DIRS or name.endswith(".egg-info"):
            ignored.add(name)
        elif any(name.startswith(p) for p in _SKIP_DIR_PREFIXES):
            ignored.add(name)
    return ignored


def materialize_overlay(*, repo_root: Path, overlay_root: Path) -> None:
    if overlay_root.exists():
        shutil.rmtree(overlay_root, ignore_errors=True)
    LOGGER.debug("materializing overlay  src=%s  dst=%s", repo_root, overlay_root)
    shutil.copytree(src=str(repo_root), dst=str(overlay_root), ignore=_ignore_patterns, symlinks=False, dirs_exist_ok=False)
    LOGGER.debug("overlay materialized  dst=%s", overlay_root)


def apply_rewrite(
    *,
    code: str,
    target_file: str,
    repo_root: Path,
    overlay_root: Path,
    mount_root: Path | None = None,
    line_start: int | None = None,
    line_end: int | None = None,
) -> Path:
    """Write code to the target file inside the overlay.

    target_file may be absolute (must be under repo_root) or relative.
    mount_root defaults to repo_root; use git root when Docker workdir is a subdir.
    When line_start/line_end are both set and the overlay file exists, only those
    lines are replaced (1-indexed, inclusive). Otherwise the full file is overwritten.
    Returns the path written inside the overlay.
    """
    target = Path(target_file).expanduser()
    if not target.is_absolute():
        target = (repo_root / target).resolve()

    base = (mount_root or repo_root).resolve()
    try:
        rel = target.relative_to(base)
    except ValueError as exc:
        raise ValueError(f"target_file {target} is not under mount_root {base}") from exc

    overlay_target = overlay_root / rel
    overlay_target.parent.mkdir(parents=True, exist_ok=True)

    if line_start is not None and line_end is not None and overlay_target.exists():
        existing_lines = overlay_target.read_text(encoding="utf-8").splitlines(keepends=True)
        new_block = code if code.endswith("\n") else code + "\n"
        result = "".join(existing_lines[:line_start - 1]) + new_block + "".join(existing_lines[line_end:])
        overlay_target.write_text(result, encoding="utf-8")
        LOGGER.debug("patch applied (targeted)  overlay_target=%s  lines=%d-%d  bytes=%d", overlay_target, line_start, line_end, len(code))
    else:
        overlay_target.write_text(code, encoding="utf-8")
        LOGGER.debug("patch applied (full rewrite)  overlay_target=%s  bytes=%d", overlay_target, len(code))

    return overlay_target


def cleanup_overlay(overlay_root: Path) -> None:
    try:
        shutil.rmtree(overlay_root, ignore_errors=True)
        LOGGER.debug("overlay cleaned up  path=%s", overlay_root)
    except Exception as exc:  # pragma: no cover
        LOGGER.warning("overlay cleanup failed  path=%s  err=%s", overlay_root, exc)


def apply_line_range_rewrite(
    *,
    code: str,
    original_path: Path,
    line_start: int | None,
    line_end: int | None,
) -> str:
    """Return full patched file content applying code to the given line range.

    If line_start/line_end are set and original_path exists, replaces only those
    lines (1-indexed, inclusive). Otherwise returns code as-is (full file replacement).
    """
    if line_start is not None and line_end is not None and original_path.exists():
        original_lines = original_path.read_text(encoding="utf-8").splitlines(keepends=True)
        if line_end > len(original_lines):
            LOGGER.warning("line_end=%d exceeds file length=%d in %s — trailing content may be truncated", line_end, len(original_lines), original_path)
        new_block = code if code.endswith("\n") else code + "\n"
        return "".join(original_lines[:line_start - 1]) + new_block + "".join(original_lines[line_end:])
    return code
