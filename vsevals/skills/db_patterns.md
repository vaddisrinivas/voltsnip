# VoltSnip Skill — Database Patterns Bug-Fix Memory

You are fixing a **db_patterns** bug: transaction lifecycle, session management, N+1 queries,
commit/rollback correctness, or connection pool hygiene.

## You MUST retrieve before writing

Before producing any code fix, call at least one retrieval tool:
- `voltsnip_fetch_by_canonical_keys` — fetch by exact key (fastest, use when keys are listed below)
- `voltsnip_semantic_search` — search by intent (use when keys are not listed or you need more context)

---

## Database Patterns Retrieval Guidance

**What to look for:** async session context managers, `async with session.begin()`, eager-load
strategies (selectinload/joinedload), explicit commit before response, rollback on exception,
connection pool `pre_ping`, N+1 avoidance via batch queries.

**Targeted search queries:**
- `"database transaction commit rollback session"`
- `"avoid N+1 eager load selectinload joinedload"`
- `"async session context manager begin"`
- `"SQLAlchemy session lifecycle close expire"`

**Key prefix for this category:** `voltsnip/bug22/category/db_patterns/`

---

## Snippet Keys for This Task

{{SNIPPET_KEY_COUNT}} canonical snippet(s) identified for this task:

{{SNIPPET_KEYS_BULLETS}}

Fetch these first with `voltsnip_fetch_by_canonical_keys`.
If a key returns nothing, fall back to `voltsnip_semantic_search` using one of the queries above.

---

## Execution Contract

1. Call `voltsnip_fetch_by_canonical_keys` with the listed keys above.
2. If results are sparse, call `voltsnip_semantic_search` with a focused DB patterns query.
3. Apply the retrieved transaction/session pattern directly — adapt only variable/class names.
4. Keep your fix minimal and localized to the stated bug target lines.
5. Emit exactly one JSON: `{"code": "<full file>", "comments": "<one-line rationale>"}`.
