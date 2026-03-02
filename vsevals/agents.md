# VoltSnip AGENT Workflow (Static, No Prelisted Keys)

You are in tool-assisted agent mode.
Use MCP tools to retrieve just enough context to produce a correct, minimal fix.
Do not assume pre-fetched memory exists.

## Agent Priorities

1. Understand exact bug objective and constraints.
2. Retrieve targeted context via MCP tools.
3. Validate fit against local code.
4. Implement minimal deterministic fix.
5. Return strictly formatted JSON output.

## MCP Tooling Model

Discovery:
- `mcp__voltsnip__search_memory`

Precision retrieval:
- `mcp__voltsnip__get_snippet_by_canonical_key`

Repository verification (when available):
- `read_file`, `glob_files`, `grep_files`

Operational rule:
- Discovery first, precision second, code edit last.

## Agent Execution Loop

1. Parse task objective, target scope, and behavioral expectation.
2. Run one focused `search_memory` call based on bug semantics.
3. Inspect candidate results; choose the best semantic match.
4. Inspect local code using read/search tools to map integration points.
5. If context is still incomplete, run one refined retrieval.
6. Apply fix with minimal footprint.
7. Re-check against objective and output constraints.
8. Emit final JSON payload.

## Category Reference (Targeted Search Intents)

- `http_resilience`: `"retry exponential backoff jitter idempotent status codes"`
- `db_patterns`: `"database transaction session commit rollback N+1"`
- `error_contracts`: `"error payload contract HTTP status serializable"`
- `logging_privacy`: `"structured log PII redact correlation severity"`
- `concurrency_cache`: `"cache stampede TTL task-local thread isolation"`

Use these as seed intents. Adapt wording to task-specific failure mode.

## Retrieval Decision Rules

Call `search_memory` when:
- You need pattern discovery.
- Task semantics are clear but implementation approach is uncertain.

Call `get_snippet_by_canonical_key` when:
- You already have a valid canonical key from prior tool output.
- You need a complete snippet for high-fidelity adaptation.

Do not:
- Guess canonical keys.
- Spam repeated low-information searches.

## Local Code Verification Rules

Before editing:
- Confirm exact target behavior in current implementation.
- Confirm surrounding call sites and data contracts.
- Identify edge cases implied by the task (bounds, error paths, race windows, privacy constraints).

After editing:
- Ensure fix is scoped and contract-preserving.
- Ensure no unrelated behavior drift.

## Quality Guardrails

- Prefer correctness over cleverness.
- Prefer deterministic logic over non-deterministic shortcuts.
- Avoid broad refactors unless task explicitly requires them.
- Do not introduce speculative abstractions.

## MCP Failure / Low-Signal Handling

If retrieval quality is poor:
- Rephrase query with stronger behavioral constraints.
- Add one discriminative keyword from failure mode.
- Run at most one refined follow-up before proceeding.

If MCP tool errors occur:
- Retry once with reduced payload complexity.
- Continue with best available evidence if persistent errors remain.

## Efficiency and Budgeting

- One strong retrieval + one verification pass usually beats many exploratory calls.
- Stop retrieving once you can justify a concrete fix.
- Keep tool usage purposeful and auditable.

## Output Contract

- Output must be a single JSON object in the required schema.
- No markdown, no additional prose, no diff format.
- When target file constraints require full-file output, provide full rewritten file.
- When line-range constraints are specified, output only replacement for that range.

## Final Self-Check Before Emitting

- Does the change satisfy the stated bug objective?
- Is the change minimal and localized?
- Is output format exactly compliant?
- Did retrieval meaningfully inform the implementation?
