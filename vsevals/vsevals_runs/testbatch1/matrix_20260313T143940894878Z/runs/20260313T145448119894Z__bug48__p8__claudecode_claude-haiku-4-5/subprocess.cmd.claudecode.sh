#!/usr/bin/env bash
# Auto-generated — reproduces the exact claudecode subprocess invocation.
cd /var/folders/kj/vs2s56dd2sb2d8vymk714fyc0000gn/T/vsevals_claudecode_wd_l7lv_m9f
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

Task ID: BUG48
Task Name: migration_version_lexicographic_and_audit
Task Objective:
Apply only this task fix using configured target file and line range.
Keep API and behavior stable except for this bug requirement.
Keep changes minimal, deterministic, and production-safe.

Task Description:
Fix MigrationRunner.get_pending_migrations so versions are compared numerically and each applied migration is audit-logged.

Target File: data/migration_runner.py

Target Lines:
36-55 (1-based, inclusive)
IMPORTANT: Output ONLY the replacement for lines 36-55 in "code".
Do NOT output the full file. Imports and surrounding lines outside this range are preserved automatically.

Test Command:
uv run pytest -q tests/unit/test_bug48.py -k bug_48

Context Code:
```python
def get_pending_migrations(self) -> list[dict[str, Any]]:
    """Return migrations not yet applied, sorted by version.

    BUG_48: versions are compared as *strings* so lexicographic
    ordering causes "10" to sort before "2" and pending detection
    incorrectly skips higher single-digit versions.
    """
    if not self.applied_versions:
        return sorted(
            self.available_migrations,
            key=lambda m: str(m["version"]),  # BUG_48: lexicographic sort
        )

    max_applied = max(self.applied_versions)  # BUG_48: string max — "9" > "10"
    pending = [
        m
        for m in self.available_migrations
        if str(m["version"]) > max_applied  # BUG_48: string comparison
    ]
    return sorted(pending, key=lambda m: str(m["version"]))
```

Target File Content (full file):
```python
"""Database schema migration runner.

Discovers pending migrations by comparing applied versions against the
available migration manifests, then executes them in version order.
Each applied migration must be recorded in the org compliance audit log.
"""
from __future__ import annotations

from typing import Any, Sequence


class MigrationRunner:
    """Run pending schema migrations in version order.

    Parameters
    ----------
    applied_versions:
        Set of version strings that have already been applied to the database.
    available_migrations:
        Sequence of dicts with ``"version"`` (string like ``"1"``, ``"2"``,
        ``"10"``) and ``"sql"`` keys describing each migration.
    """

    def __init__(
        self,
        applied_versions: set[str],
        available_migrations: Sequence[dict[str, Any]],
    ) -> None:
        self.applied_versions = applied_versions
        self.available_migrations = available_migrations

    # ------------------------------------------------------------------
    # Core public API
    # ------------------------------------------------------------------

    def get_pending_migrations(self) -> list[dict[str, Any]]:
        """Return migrations not yet applied, sorted by version.

        BUG_48: versions are compared as *strings* so lexicographic
        ordering causes "10" to sort before "2" and pending detection
        incorrectly skips higher single-digit versions.
        """
        if not self.applied_versions:
            return sorted(
                self.available_migrations,
                key=lambda m: str(m["version"]),  # BUG_48: lexicographic sort
            )

        max_applied = max(self.applied_versions)  # BUG_48: string max — "9" > "10"
        pending = [
            m
            for m in self.available_migrations
            if str(m["version"]) > max_applied  # BUG_48: string comparison
        ]
        return sorted(pending, key=lambda m: str(m["version"]))

    def apply_pending(self, executor: Any) -> list[str]:
        """Apply all pending migrations and return the applied versions.

        Parameters
        ----------
        executor:
            Object with an ``execute(sql)`` method used to run each
            migration'"'"'s SQL statement.

        Returns
        -------
        list[str]
            Version strings of migrations that were applied.
        """
        pending = self.get_pending_migrations()
        applied: list[str] = []
        for migration in pending:
            version = str(migration["version"])
            executor.execute(migration["sql"])
            self.applied_versions.add(version)
            applied.append(version)
        return applied
```

Expected Output:
Use int() for version comparison and sorting AND call orgops.auditing.write_event("migration.applied", version=version) for each migration.

Execution Mode:
Agent mode: decide context/tool usage within constraints.

Variant Hypothesis:
P4 + explicit instruction — plugin skill + explicit framing.

Tool Budget:
Maximum tool roundtrips: 4

Execution Instruction:
This is strict: you MUST invoke the voltsnip-guide skill to retrieve relevant code patterns and context before implementing the fix. Do not attempt the fix without first consulting the skill.
Keep output deterministic and minimal.' --dangerously-skip-permissions --output-format stream-json --verbose --model claude-haiku-4-5 --allowedTools mcp__voltsnip__search_memory,mcp__voltsnip__get_snippet_by_canonical_key,mcp__voltsnip__semantic_search_api_v1_search_semantic_get,mcp__voltsnip__search_api_v1_search,mcp__voltsnip__read_snippet_api_v1_snippets,mcp__voltsnip__read_snippet_by_canonical_key_api_v1_snippets_by_key,mcp__voltsnip__view_snippet_api_v1_snippets,Skill --disallowedTools Bash,Edit,Write,NotebookEdit,WebFetch,WebSearch,TodoWrite,Task,TaskOutput,TaskStop,AskUserQuestion,EnterPlanMode,ExitPlanMode,EnterWorktree,ReadMcpResourceTool,ListMcpResourcesTool --mcp-config /var/folders/kj/vs2s56dd2sb2d8vymk714fyc0000gn/T/tmpkp88ovmh.json --plugin-dir /var/folders/kj/vs2s56dd2sb2d8vymk714fyc0000gn/T/vsevals_claudecode_wd_l7lv_m9f
