# VoltSnip Skill — Concurrency & Cache Bug-Fix Memory

You are fixing a **concurrency_cache** bug: cache stampede, TTL semantics, task-local context
isolation, thread-safety, or async lock correctness.

## You MUST retrieve before writing

Before producing any code fix, call at least one retrieval tool:
- `voltsnip_fetch_by_canonical_keys` — fetch by exact key (fastest, use when keys are listed below)
- `voltsnip_semantic_search` — search by intent (use when keys are not listed or you need more context)

---

## Concurrency & Cache Retrieval Guidance

**What to look for:** single-flight / request coalescing to prevent stampede, TTL-aware cache
with stale-while-revalidate, `contextvars.ContextVar` for task-local state, `asyncio.Lock` per
cache key (not global), negative caching for missing keys, atomic compare-and-set patterns.

**Targeted search queries:**
- `"cache TTL stampede coalesce task local context"`
- `"asyncio lock per key single flight"`
- `"ContextVar task local thread isolation"`
- `"stale while revalidate negative cache TTL"`

**Key prefix for this category:** `voltsnip/bug22/category/concurrency_cache/`

---

## Snippet Keys for This Task

{{SNIPPET_KEY_COUNT}} canonical snippet(s) identified for this task:

{{SNIPPET_KEYS_BULLETS}}

Fetch these first with `voltsnip_fetch_by_canonical_keys`.
If a key returns nothing, fall back to `voltsnip_semantic_search` using one of the queries above.

---

## Execution Contract

1. Call `voltsnip_fetch_by_canonical_keys` with the listed keys above.
2. If results are sparse, call `voltsnip_semantic_search` with a focused concurrency/cache query.
3. Apply the retrieved stampede-prevention/TTL pattern directly — adapt only variable names.
4. Keep your fix minimal and localized to the stated bug target lines.
5. Emit exactly one JSON: `{"code": "<full file>", "comments": "<one-line rationale>"}`.
