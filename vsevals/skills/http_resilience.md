# VoltSnip Skill — HTTP Resilience Bug-Fix Memory

You are fixing an **http_resilience** bug: retry logic, exponential backoff, jitter, circuit
breakers, or idempotency handling.

## You MUST retrieve before writing

Before producing any code fix, call at least one retrieval tool:
- `voltsnip_fetch_by_canonical_keys` — fetch by exact key (fastest, use when keys are listed below)
- `voltsnip_semantic_search` — search by intent (use when keys are not listed or you need more context)

---

## HTTP Resilience Retrieval Guidance

**What to look for:** retry decorators, backoff schedules with jitter, idempotency key propagation,
status-code retry sets (5xx + 429 + 408), circuit-breaker open/half-open transitions.

**Targeted search queries:**
- `"retry exponential backoff jitter idempotent"`
- `"circuit breaker timeout half-open"`
- `"retry on 429 503 408 status code"`
- `"requests session retry adapter max attempts"`

**Key prefix for this category:** `voltsnip/bug22/category/http_resilience/`

---

## Snippet Keys for This Task

{{SNIPPET_KEY_COUNT}} canonical snippet(s) identified for this task:

{{SNIPPET_KEYS_BULLETS}}

Fetch these first with `voltsnip_fetch_by_canonical_keys`.
If a key returns nothing, fall back to `voltsnip_semantic_search` using one of the queries above.

---

## Execution Contract

1. Call `voltsnip_fetch_by_canonical_keys` with the listed keys above.
2. If results are sparse, call `voltsnip_semantic_search` with a focused HTTP resilience query.
3. Apply the retrieved retry/backoff pattern directly — adapt only variable/class names.
4. Keep your fix minimal and localized to the stated bug target lines.
5. Emit exactly one JSON: `{"code": "<full file>", "comments": "<one-line rationale>"}`.
