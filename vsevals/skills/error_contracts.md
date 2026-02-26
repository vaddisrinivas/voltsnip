# VoltSnip Skill — Error Contracts Bug-Fix Memory

You are fixing an **error_contracts** bug: error response payloads, HTTP status code mapping,
consistent JSON error shapes, or exception-to-response serialization.

## You MUST retrieve before writing

Before producing any code fix, call at least one retrieval tool:
- `voltsnip_fetch_by_canonical_keys` — fetch by exact key (fastest, use when keys are listed below)
- `voltsnip_semantic_search` — search by intent (use when keys are not listed or you need more context)

---

## Error Contracts Retrieval Guidance

**What to look for:** standardized error response schemas (`{"error": ..., "detail": ...}`),
HTTP status code mappings (400/401/403/404/422/500), exception handlers that produce consistent
JSON, typed error payloads with `code`/`message`/`details` fields.

**Targeted search queries:**
- `"error response contract status code mapping"`
- `"consistent error payload JSON serializable"`
- `"exception handler HTTP status code FastAPI"`
- `"error schema code message detail typed"`

**Key prefix for this category:** `voltsnip/bug22/category/error_contracts/`

---

## Snippet Keys for This Task

{{SNIPPET_KEY_COUNT}} canonical snippet(s) identified for this task:

{{SNIPPET_KEYS_BULLETS}}

Fetch these first with `voltsnip_fetch_by_canonical_keys`.
If a key returns nothing, fall back to `voltsnip_semantic_search` using one of the queries above.

---

## Execution Contract

1. Call `voltsnip_fetch_by_canonical_keys` with the listed keys above.
2. If results are sparse, call `voltsnip_semantic_search` with a focused error contracts query.
3. Apply the retrieved error-payload/status-mapping pattern directly — adapt only class names.
4. Keep your fix minimal and localized to the stated bug target lines.
5. Emit exactly one JSON: `{"code": "<full file>", "comments": "<one-line rationale>"}`.
