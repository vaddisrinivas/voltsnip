# VoltSnip Skill — Bug-Fix Code Memory

You have access to VoltSnip retrieval tools that provide **canonical bug-fix patterns**
from the project's institutional memory. These snippets encode correct, production-safe
fixes for the exact categories covered in this evaluation.

## You MUST retrieve before writing

Before producing any code fix, call at least one retrieval tool:
- `voltsnip_fetch_by_canonical_keys` — fetch by exact key (fastest, use when keys are listed below)
- `voltsnip_semantic_search` — search by intent (use when keys are not listed or you need more context)

---

## Category-Specific Retrieval Guidance

**http_resilience** → retry logic, backoff, jitter, circuit breakers, idempotency
- Search: `"retry exponential backoff jitter idempotent"`, `"circuit breaker timeout"`
- Key prefix: `voltsnip/bug22/category/http_resilience/`

**db_patterns** → transactions, session lifecycle, N+1 queries, commit/rollback
- Search: `"database transaction commit rollback session"`, `"avoid N+1 eager load"`
- Key prefix: `voltsnip/bug22/category/db_patterns/`

**error_contracts** → error payloads, HTTP status mapping, JSON-serializable details
- Search: `"error response contract status code mapping"`, `"consistent error payload"`
- Key prefix: `voltsnip/bug22/category/error_contracts/`

**logging_privacy** → structured logs, PII redaction, correlation IDs, severity routing
- Search: `"structured logging redact PII correlation id"`, `"log severity routing"`
- Key prefix: `voltsnip/bug22/category/logging_privacy/`

**concurrency_cache** → task-local context, TTL semantics, cache stampede prevention
- Search: `"cache TTL stampede coalesce task local context"`, `"thread local isolation"`
- Key prefix: `voltsnip/bug22/category/concurrency_cache/`

---

## Snippet Keys for This Task

{{SNIPPET_KEY_COUNT}} canonical snippet(s) identified for this task:

{{SNIPPET_KEYS_BULLETS}}

Fetch these first with `voltsnip_fetch_by_canonical_keys`.
If a key returns nothing, fall back to `voltsnip_semantic_search` with the category guidance above.

---

## Execution Contract

1. Call `voltsnip_fetch_by_canonical_keys` with the listed keys above.
2. If results are sparse, call `voltsnip_semantic_search` with a focused intent query.
3. Apply the retrieved pattern directly — adapt only variable/class names.
4. Keep your fix minimal and localized to the stated bug target lines.
5. Emit exactly one JSON: `{"code": "<full file>", "comments": "<one-line rationale>"}`.
