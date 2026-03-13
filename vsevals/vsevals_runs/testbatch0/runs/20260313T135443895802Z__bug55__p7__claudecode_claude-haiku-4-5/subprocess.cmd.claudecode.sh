#!/usr/bin/env bash
# Auto-generated — reproduces the exact claudecode subprocess invocation.
cd /var/folders/kj/vs2s56dd2sb2d8vymk714fyc0000gn/T/vsevals_claudecode_wd_nnba_pto
export ANTHROPIC_API_KEY=''
export NO_COLOR=1
export CLAUDE_MODEL=claude-haiku-4-5
exec claude -p 'You are a senior software engineer executing a controlled code-fix evaluation.

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

Tool access is enabled. Fetch memory through tools when useful to solve the task.

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
P3 + explicit instruction — tests if framing alone improves unguided tool use.

Tool Budget:
Maximum tool roundtrips: 4

Execution Instruction:
This is strict: satisfy the acceptance criteria and expected output exactly.
Keep output deterministic and minimal.' --dangerously-skip-permissions --output-format stream-json --verbose --model claude-haiku-4-5 --allowedTools mcp__voltsnip__search_memory,mcp__voltsnip__get_snippet_by_canonical_key,mcp__voltsnip__semantic_search_api_v1_search_semantic_get,mcp__voltsnip__search_api_v1_search,mcp__voltsnip__read_snippet_api_v1_snippets,mcp__voltsnip__read_snippet_by_canonical_key_api_v1_snippets_by_key,mcp__voltsnip__view_snippet_api_v1_snippets --disallowedTools Bash,Edit,Write,NotebookEdit,WebFetch,WebSearch,TodoWrite,Task,TaskOutput,TaskStop,AskUserQuestion,Skill,EnterPlanMode,ExitPlanMode,EnterWorktree,ReadMcpResourceTool,ListMcpResourcesTool --mcp-config /var/folders/kj/vs2s56dd2sb2d8vymk714fyc0000gn/T/tmppjt5y116.json
