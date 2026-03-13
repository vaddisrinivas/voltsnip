"""Isolated overlay patching for pytest runs.

Strategy: full_file_rewrite + isolated_overlay
  1. Copy the repo to an overlay directory (inside the run artifact dir).
  2. Write the LLM-generated code to the target file inside the overlay.
  3. Run pytest in Docker, mounting the overlay as the workspace.
  4. Discard the overlay when done (or keep for debugging).

The original repo is never modified.  This makes concurrent matrix runs safe
without any file-system locking.

Public API
----------
  materialize_overlay(repo_root, overlay_root)
      Copy the repo into overlay_root, skipping heavy/sensitive dirs.

  apply_rewrite(code, target_file, repo_root, overlay_root)
      Write `code` to the corresponding path inside overlay_root.

  cleanup_overlay(overlay_root)
      Remove the overlay directory tree.
"""

from __future__ import annotations

import logging
import shutil
from pathlib import Path

LOGGER = logging.getLogger(__name__)

# Directories to skip when copying the repo into the overlay.
_SKIP_DIRS = frozenset({
    ".git",
    ".venv",
    "venv",
    ".tox",
    "node_modules",
    "__pycache__",
    ".mypy_cache",
    ".ruff_cache",
    ".pytest_cache",
    "dist",
    "build",
    ".eggs",
    "*.egg-info",  # matched by name startswith check below
    "htmlcov",
    ".coverage",
})

_SKIP_DIR_PREFIXES = (".", "__pycache__")


def _ignore_patterns(src: str, names: list[str]) -> set[str]:
    """shutil.copytree ignore callback — prune heavy / irrelevant subtrees."""
    ignored: set[str] = set()
    for name in names:
        if name in _SKIP_DIRS:
            ignored.add(name)
            continue
        if name.endswith(".egg-info"):
            ignored.add(name)
            continue
        if any(name.startswith(prefix) for prefix in _SKIP_DIR_PREFIXES):
            ignored.add(name)
    return ignored


def materialize_overlay(*, repo_root: Path, overlay_root: Path) -> None:
    """Copy the entire repo into overlay_root, skipping heavy directories.

    overlay_root must not exist yet (or be an empty directory).
    """
    if overlay_root.exists():
        shutil.rmtree(overlay_root, ignore_errors=True)

    LOGGER.debug("materializing overlay  src=%s  dst=%s", repo_root, overlay_root)
    shutil.copytree(
        src=str(repo_root),
        dst=str(overlay_root),
        ignore=_ignore_patterns,
        symlinks=False,
        dirs_exist_ok=False,
    )
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
    """Write `code` to the target file inside the overlay.

    Parameters
    ----------
    code:
        The LLM-generated code to write.
    target_file:
        Path to the target file.  Can be absolute (must be under repo_root)
        or relative (resolved against repo_root).
    repo_root:
        Absolute path to the original repo root.  Used to resolve relative
        target_file paths.
    overlay_root:
        Absolute path to the overlay root (what gets mounted at /workspace).
    mount_root:
        The ancestor directory that was copied into overlay_root.  If None,
        defaults to repo_root.  Use the git root when the Docker workdir is
        a subdirectory of /workspace (e.g. /workspace/voltsnip-evals/usecases/…).
    line_start, line_end:
        1-indexed, inclusive line range to replace.  When both are provided
        and the overlay file already exists, only the target lines are replaced;
        the surrounding file content is preserved.  This prevents a full-file
        rewrite from wiping unrelated code when the task only targets a
        function or block.
        When either is None, the entire file is overwritten with `code`.

    Returns
    -------
    Path
        The path written inside the overlay.
    """
    target = Path(target_file).expanduser()
    if not target.is_absolute():
        target = (repo_root / target).resolve()

    # Compute path relative to mount_root, then mirror into overlay
    base = (mount_root or repo_root).resolve()
    try:
        rel = target.relative_to(base)
    except ValueError as exc:
        raise ValueError(
            f"target_file {target} is not under mount_root {base}"
        ) from exc

    overlay_target = overlay_root / rel
    overlay_target.parent.mkdir(parents=True, exist_ok=True)

    if line_start is not None and line_end is not None and overlay_target.exists():
        # Targeted rewrite: replace only lines [line_start, line_end] (1-indexed, inclusive).
        # Lines outside the range are preserved verbatim.
        existing_lines = overlay_target.read_text(encoding="utf-8").splitlines(keepends=True)
        before = existing_lines[:line_start - 1]
        after = existing_lines[line_end:]  # line_end is inclusive → skip it
        # Ensure the new code block ends with a newline so surrounding lines join cleanly.
        new_block = code if code.endswith("\n") else code + "\n"
        result = "".join(before) + new_block + "".join(after)
        overlay_target.write_text(result, encoding="utf-8")
        LOGGER.debug(
            "patch applied (targeted)  overlay_target=%s  lines=%d-%d  bytes=%d",
            overlay_target, line_start, line_end, len(code),
        )
    else:
        # Full file rewrite (no line range set, or file not yet in overlay)
        overlay_target.write_text(code, encoding="utf-8")
        LOGGER.debug(
            "patch applied (full rewrite)  overlay_target=%s  bytes=%d",
            overlay_target, len(code),
        )

    return overlay_target


def cleanup_overlay(overlay_root: Path) -> None:
    """Remove the overlay directory tree (best-effort, ignores errors)."""
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
    """Produce the full patched file content by applying the generated code.

    If line_start and line_end are set and original_path exists, replaces only
    those lines (1-indexed, inclusive) with the generated code; lines outside
    the range are preserved verbatim.

    If no line range is given, returns ``code`` as-is (full file replacement).

    Parameters
    ----------
    code:
        The LLM-generated code block.
    original_path:
        Path to the original source file on the host (read-only; never modified).
    line_start / line_end:
        1-indexed inclusive line range to replace.  Both must be set to
        activate targeted rewrite.

    Returns
    -------
    str
        Full file content to write to the patched file.
    """
    if line_start is not None and line_end is not None and original_path.exists():
        original_lines = original_path.read_text(encoding="utf-8").splitlines(keepends=True)
        if line_end > len(original_lines):
            LOGGER.warning(
                "line_end=%d exceeds file length=%d in %s — trailing content may be truncated",
                line_end, len(original_lines), original_path,
            )
        before = original_lines[:line_start - 1]
        after = original_lines[line_end:]  # line_end is inclusive → skip it
        new_block = code if code.endswith("\n") else code + "\n"
        return "".join(before) + new_block + "".join(after)

    return code
