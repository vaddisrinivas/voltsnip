#!/usr/bin/env bash
# Auto-generated — reproduces the exact codex subprocess invocation.
cd /var/folders/kj/vs2s56dd2sb2d8vymk714fyc0000gn/T/vsevals_codex_wd_4_v365qn
exec codex -a never exec --model gpt-5.2-codex --json --ephemeral --skip-git-repo-check --disable shell_tool -o /Users/srinivasvaddi/Projects/moltsnip_root/vsevals/vsevals_runs/testbatch2/matrix_20260313T155518271339Z/runs/20260313T160503894313Z__bug59__p8__codex_gpt-5.2-codex/codex_last_message.txt --output-schema /var/folders/kj/vs2s56dd2sb2d8vymk714fyc0000gn/T/vsevals_codex_schema_coe7ylnp.json -C /var/folders/kj/vs2s56dd2sb2d8vymk714fyc0000gn/T/vsevals_codex_wd_4_v365qn --sandbox read-only --disable unified_exec -c 'mcp_servers={}' -c mcp_servers.voltsnip.url=http://127.0.0.1:63089/mcp 'You are a senior software engineer executing a controlled code-fix evaluation.

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

Task ID: BUG59
Task Name: http_status_classification_and_metric
Task Objective:
Apply only this task fix using configured target file and line range.
Keep API and behavior stable except for this bug requirement.
Keep changes minimal, deterministic, and production-safe.

Task Description:
Fix classify_http_error to split 4xx (client_error) from 5xx (server_error) instead of lumping both as server_error.

Target File: errors/error_mapper.py

Target Lines:
27-42 (1-based, inclusive)
IMPORTANT: Output ONLY the replacement for lines 27-42 in "code".
Do NOT output the full file. Imports and surrounding lines outside this range are preserved automatically.

Test Command:
uv run pytest -q tests/unit/test_bug59.py -k bug_59

Context Code:
```python
def classify_http_error(status_code: int) -> str:
    """Classify an HTTP status code into an error category.

    Expected categories:
        - "client_error"  for 400-499
        - "server_error"  for 500-599
        - "unknown"       for anything else

    BUG_59: the implementation lumps ALL codes 400-599 into "server_error"
    instead of splitting 4xx (client) from 5xx (server).  Models must
    also emit an "error.mapped" metric via orgops.metrics.emit().
    """
    # BUG_59: treats 4xx and 5xx identically as server_error
    if 400 <= status_code < 600:
        return "server_error"
    return "unknown"
```

Target File Content (full file):
```python
"""HTTP error classification and structured error response building.

This module provides status-code classification for the org error pipeline.
Callers use `classify_http_error` to map raw status codes to canonical
error categories that drive alerting, dashboards, and SLA accounting.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ErrorResponse:
    """Immutable structured error returned to callers."""

    category: str
    status_code: int
    message: str
    retryable: bool


# Codes the org considers safe to retry automatically.
RETRYABLE_CODES: frozenset[int] = frozenset({408, 429, 500, 502, 503, 504})


def classify_http_error(status_code: int) -> str:
    """Classify an HTTP status code into an error category.

    Expected categories:
        - "client_error"  for 400-499
        - "server_error"  for 500-599
        - "unknown"       for anything else

    BUG_59: the implementation lumps ALL codes 400-599 into "server_error"
    instead of splitting 4xx (client) from 5xx (server).  Models must
    also emit an "error.mapped" metric via orgops.metrics.emit().
    """
    # BUG_59: treats 4xx and 5xx identically as server_error
    if 400 <= status_code < 600:
        return "server_error"
    return "unknown"


def build_error_response(
    status_code: int,
    detail: str = "",
) -> ErrorResponse:
    """Build a structured ErrorResponse for the given status code.

    Combines classification with retryability to give callers a
    single object they can log, return, or feed to the retry layer.
    """
    category = classify_http_error(status_code)
    retryable = status_code in RETRYABLE_CODES
    message = detail or f"HTTP {status_code}"
    return ErrorResponse(
        category=category,
        status_code=status_code,
        message=message,
        retryable=retryable,
    )


def error_summary(responses: list[ErrorResponse]) -> dict[str, Any]:
    """Aggregate a list of ErrorResponse objects into a summary dict."""
    if not responses:
        return {"total": 0, "by_category": {}}
    by_cat: dict[str, int] = {}
    for r in responses:
        by_cat[r.category] = by_cat.get(r.category, 0) + 1
    return {
        "total": len(responses),
        "by_category": by_cat,
        "retryable_count": sum(1 for r in responses if r.retryable),
    }
```

Expected Output:
Split 4xx as client_error from 5xx as server_error AND emit error.mapped metric.

Execution Mode:
Agent mode: decide context/tool usage within constraints.

Variant Hypothesis:
P4 + explicit instruction — plugin skill + explicit framing.

Tool Budget:
Maximum tool roundtrips: 4

Execution Instruction:
This is strict: you MUST invoke the voltsnip-guide skill to retrieve relevant code patterns and context before implementing the fix. Do not attempt the fix without first consulting the skill.
Keep output deterministic and minimal.'
