#!/usr/bin/env bash
# Auto-generated — reproduces the exact codex subprocess invocation.
cd /var/folders/kj/vs2s56dd2sb2d8vymk714fyc0000gn/T/vsevals_codex_wd_etakczwv
exec codex -a never exec --model gpt-5.2-codex --json --ephemeral --skip-git-repo-check --disable shell_tool -o /Users/srinivasvaddi/Projects/moltsnip_root/vsevals/vsevals_runs/testbatch0/runs/20260313T141824752493Z__bug55__p4__codex_gpt-5.2-codex/codex_last_message.txt --output-schema /var/folders/kj/vs2s56dd2sb2d8vymk714fyc0000gn/T/vsevals_codex_schema_80qxoymt.json -C /var/folders/kj/vs2s56dd2sb2d8vymk714fyc0000gn/T/vsevals_codex_wd_etakczwv --sandbox read-only --disable unified_exec -c 'mcp_servers={}' -c mcp_servers.voltsnip.url=http://127.0.0.1:60837/mcp 'You are a senior software engineer executing a controlled code-fix evaluation.

Output format:
Return ONLY valid JSON — no markdown fences, preamble, or trailing text:
{"code": "<see editing contract below>", "comments": "<one-sentence explanation of the change>"}

Editing contract:
- When NO Target Lines are given: "code" must be the complete rewritten file content.
- When Target Lines ARE given: "code" must contain ONLY the replacement for that line range.
  The file header, imports, and all content outside the range are preserved automatically.
  Do NOT include them — outputting the full file will corrupt the target file.
- Never return a diff, patch, pseudocode, placeholder, or partial line fragment.
- Keep changes minimal and localized to the stated bug objective.
- Preserve public behavior unless the task explicitly requires a change.

Reliability contract:
- Prefer deterministic fixes over clever rewrites.
- Preserve imports, typing, and runtime safety.
- If uncertain, preserve existing behavior and avoid speculative refactors.

Task ID: BUG55
Task Name: stampede_threshold_inverted_and_metric
Task Objective:
Apply only this task fix using configured target file and line range.
Keep API and behavior stable except for this bug requirement.
Keep changes minimal, deterministic, and production-safe.

Task Description:
Fix should_refresh_early so entries refresh when close to expiry, not far from it.

Target File: cache/stampede_guard.py

Target Lines:
34-57 (1-based, inclusive)
IMPORTANT: Output ONLY the replacement for lines 34-57 in "code".
Do NOT output the full file. Imports and surrounding lines outside this range are preserved automatically.

Test Command:
uv run pytest -q tests/unit/test_bug55.py -k bug_55

Context Code:
```python
def should_refresh_early(
    self,
    time_remaining: float,
    ttl: float,
    key_name: str = "unknown",
) -> bool:
    """Return True when the entry should be refreshed before expiry.

    BUG_55: the ratio comparison is inverted, causing early refreshes
    when the entry is FAR from expiry (most of the TTL left) rather
    than CLOSE to expiry (little TTL left).
    """
    if ttl <= 0:
        return False

    ratio = time_remaining / ttl

    # BUG_55: inverted comparison -- refreshes when ratio is HIGH
    # (far from expiry) instead of when ratio is LOW (close to expiry)
    if ratio > self.threshold:  # BUG_55: should be < not >
        self.refreshes_triggered += 1
        return True

    return False
```

Target File Content (full file):
```python
"""Stampede guard for cache early-refresh decisions.

This module provides probabilistic early refresh to prevent cache
stampede scenarios.  When a cached entry is close to expiry, the guard
triggers an early refresh so the new value is ready before the old one
expires.  The operational metrics pipeline is notified whenever an
early refresh is triggered.
"""
from __future__ import annotations

from typing import Any


class StampedeGuard:
    """Decides whether to refresh a cache entry before its TTL expires.

    The core heuristic: when the *remaining* fraction of the TTL drops
    below a configurable *threshold*, trigger an early refresh to avoid
    a thundering-herd on expiry.

    Usage::

        guard = StampedeGuard(threshold=0.2)
        if guard.should_refresh_early(time_remaining=2.0, ttl=10.0, key_name="users"):
            schedule_background_refresh("users")
    """

    def __init__(self, threshold: float = 0.2) -> None:
        if not 0.0 < threshold < 1.0:
            raise ValueError("threshold must be between 0 and 1 exclusive")
        self.threshold = threshold
        self.refreshes_triggered: int = 0

    def should_refresh_early(
        self,
        time_remaining: float,
        ttl: float,
        key_name: str = "unknown",
    ) -> bool:
        """Return True when the entry should be refreshed before expiry.

        BUG_55: the ratio comparison is inverted, causing early refreshes
        when the entry is FAR from expiry (most of the TTL left) rather
        than CLOSE to expiry (little TTL left).
        """
        if ttl <= 0:
            return False

        ratio = time_remaining / ttl

        # BUG_55: inverted comparison -- refreshes when ratio is HIGH
        # (far from expiry) instead of when ratio is LOW (close to expiry)
        if ratio > self.threshold:  # BUG_55: should be < not >
            self.refreshes_triggered += 1
            return True

        return False

    @property
    def stats(self) -> dict[str, Any]:
        """Return guard statistics."""
        return {
            "threshold": self.threshold,
            "refreshes_triggered": self.refreshes_triggered,
        }
```

Expected Output:
Fix comparison from > to < for correct early-refresh AND emit cache.stampede.prevented metric.

Execution Mode:
Agent mode: decide context/tool usage within constraints.

Variant Hypothesis:
SKILL.md guide + tools, no key hints — model follows workflow.

Tool Budget:
Maximum tool roundtrips: 4'
