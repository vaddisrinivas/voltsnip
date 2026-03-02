"""Pure Python tool functions for the eval harness.

These are the canonical implementations of every tool available to eval
providers (codex, claudecode, etc.).  They are served as MCP tools by
HarnessMCPServer so subprocess-based providers (codex) can call them via curl.

Tools
-----
  read_file(repo_root, path, offset=0, limit=200)
  glob_files(repo_root, pattern)
  grep_files(repo_root, pattern, path=".", glob_pat="**/*")
  search_snippets(base_url, intent, language=None, tags=None)
  get_snippet_by_key(base_url, key)
"""
from __future__ import annotations

import glob as _glob
import json
import re
import urllib.error
import urllib.request
from pathlib import Path


def read_file(
    repo_root: Path,
    path: str,
    offset: int = 0,
    limit: int = 200,
) -> str:
    root = repo_root.resolve()
    p = (root / path).resolve()
    if not str(p).startswith(str(root)):
        raise PermissionError(f"path outside repo root: {path}")
    if not p.exists():
        raise FileNotFoundError(f"not found: {path}")
    lines = p.read_text(encoding="utf-8", errors="replace").splitlines()
    offset = max(0, int(offset))
    limit = min(2000, max(1, int(limit)))
    chunk = lines[offset : offset + limit]
    return "\n".join(f"{offset + i + 1}\t{ln}" for i, ln in enumerate(chunk))


def glob_files(repo_root: Path, pattern: str) -> str:
    root = repo_root.resolve()
    matches = _glob.glob(pattern, root_dir=root, recursive=True)
    return "\n".join(sorted(matches)[:500]) or "(no matches)"


def grep_files(
    repo_root: Path,
    pattern: str,
    path: str = ".",
    glob_pat: str = "**/*",
) -> str:
    root = repo_root.resolve()
    search_dir = root / path
    if not str(search_dir.resolve()).startswith(str(root)):
        raise PermissionError("path outside repo root")
    try:
        rx = re.compile(pattern)
    except re.error as exc:
        raise ValueError(f"invalid regex: {exc}") from exc
    results: list[str] = []
    for f in sorted(search_dir.glob(glob_pat)):
        if not f.is_file():
            continue
        try:
            for i, line in enumerate(f.read_text(errors="replace").splitlines(), 1):
                if rx.search(line):
                    rel = f.relative_to(root)
                    results.append(f"{rel}:{i}: {line.rstrip()}")
                    if len(results) >= 200:
                        break
        except OSError:
            pass
        if len(results) >= 200:
            break
    return "\n".join(results) or "(no matches)"


def search_snippets(
    base_url: str,
    intent: str,
    language: str | None = None,
    tags: list[str] | None = None,
) -> str:
    url = base_url.rstrip("/") + "/api/v1/search/semantic"
    payload: dict = {"q": intent, "limit": 5}
    if language:
        payload["language"] = language
    if tags:
        payload["tags"] = tags
    data = json.dumps(payload).encode()
    req = urllib.request.Request(
        url, data=data, headers={"Content-Type": "application/json"}
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return resp.read().decode()
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"VoltSnip search failed: {exc.code} {exc.reason}") from exc


def get_snippet_by_key(base_url: str, key: str) -> str:
    url = base_url.rstrip("/") + f"/api/v1/snippets/by-key/{key}"
    req = urllib.request.Request(url)
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return resp.read().decode()
    except urllib.error.HTTPError as exc:
        raise RuntimeError(
            f"VoltSnip get_snippet failed: {exc.code} {exc.reason}"
        ) from exc
