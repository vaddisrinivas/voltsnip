# VoltSnip SKILL Guidance (Static, No Prelisted Keys)

This guide defines how to use MCP retrieval effectively during bug-fix tasks.
It is intentionally static: no task-specific key lists, no repository path hints,
and no preselected snippets.

## Objective

Use MCP retrieval to gather high-signal implementation patterns, then apply a minimal,
correct, production-safe fix for the requested bug.

## MCP Tools You Can Use

Primary memory tools:
- `mcp__voltsnip__search_memory`
- `mcp__voltsnip__get_snippet_by_canonical_key`

Common repository-inspection tools (provider-dependent):
- `read_file`
- `glob_files`
- `grep_files`

Principle:
- `search_memory` is discovery.
- `get_snippet_by_canonical_key` is precision retrieval after discovery.
- File tools verify where and how to apply the pattern.

## Tool Semantics

### `mcp__voltsnip__search_memory`

Use when:
- You need relevant examples but do not know exact snippet identifiers.
- You need breadth first, then narrow.

Recommended inputs:
- `query`: concise intent statement with bug behavior + desired behavior.
- `intent`: optional alternate phrasing if available.
- `language`: include when implementation language is known.
- `tags`: include only if you have strong priors.

What good output looks like:
- Results that match bug semantics (not just lexical overlap).
- Patterns showing the same failure mode and recovery behavior.
- Implementations with clear adaptation potential.

### `mcp__voltsnip__get_snippet_by_canonical_key`

Use when:
- A prior tool output already gave an exact canonical key.
- You need the full snippet payload for faithful adaptation.

Avoid when:
- You are guessing key names.
- Discovery hasn’t happened yet.

## Category Reference (Targeted Search Intents)

- `http_resilience`: `"retry exponential backoff jitter idempotent status codes"`
- `db_patterns`: `"database transaction session commit rollback N+1"`
- `error_contracts`: `"error payload contract HTTP status serializable"`
- `logging_privacy`: `"structured log PII redact correlation severity"`
- `concurrency_cache`: `"cache stampede TTL task-local thread isolation"`

Use these as starting points. Refine query terms based on task wording and observed code.

## Retrieval Workflow

1. Read the task objective and failure mode carefully.
2. Run one focused `search_memory` call.
3. Evaluate top results for semantic fit, not keyword overlap.
4. If needed, run one refined follow-up `search_memory` call.
5. If an exact canonical key is surfaced and deeper detail is needed, call `get_snippet_by_canonical_key`.
6. Stop retrieval once confidence is sufficient.

## Query Construction Rules

- Keep query short and behavior-specific.
- Include both defect and expected correction.
- Prefer terms that encode invariants (e.g., idempotency, rollback, redaction, bounded retries).
- Avoid broad words that produce noisy matches.

## Relevance Triage Checklist

Select snippets that:
- Address the same bug class, not merely adjacent concerns.
- Show deterministic behavior under edge cases.
- Preserve external contract semantics where required.
- Can be adapted with minimal structural change.

Reject snippets that:
- Require architectural rewrites unrelated to the task.
- Change API behavior without requirement.
- Depend on assumptions not present in current code.

## Integration Rules

- Apply pattern semantics, not blind copy-paste.
- Adapt naming and local structure only as needed.
- Keep edits localized to bug-relevant scope.
- Preserve imports, typing, and surrounding behavior unless task requires change.

## Failure Handling

If retrieval is weak:
- Tighten query around explicit failure mode and expected postcondition.
- Add one discriminative term from task objective.
- Avoid repeated equivalent queries.

If tool call errors:
- Retry once with simpler payload.
- Continue with best available context if repeated failures persist.

## MCP Efficiency Rules

- Prefer one high-quality retrieval over many exploratory calls.
- Avoid duplicate calls with equivalent intent.
- Use file-inspection tools only when necessary to validate integration points.

## Output Contract

- Emit exactly one JSON object in the required schema.
- No markdown fences.
- No explanatory prose outside JSON.
- Ensure code section satisfies task line-range/full-file constraints.
