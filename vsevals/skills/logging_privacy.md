# VoltSnip Skill — Logging & Privacy Bug-Fix Memory

You are fixing a **logging_privacy** bug: structured log fields, PII redaction, correlation ID
propagation, log severity routing, or accidental sensitive-data exposure in logs.

## You MUST retrieve before writing

Before producing any code fix, call at least one retrieval tool:
- `voltsnip_fetch_by_canonical_keys` — fetch by exact key (fastest, use when keys are listed below)
- `voltsnip_semantic_search` — search by intent (use when keys are not listed or you need more context)

---

## Logging & Privacy Retrieval Guidance

**What to look for:** structlog/stdlib structured logger setup, PII field redaction (email,
phone, SSN, token scrubbing), correlation/request-id injection via context vars, severity
routing (DEBUG only to stderr, WARNING+ to alerting), log sampling for high-volume paths.

**Targeted search queries:**
- `"structured logging redact PII correlation id"`
- `"log severity routing structlog processor"`
- `"sanitize sensitive fields before logging"`
- `"correlation id context var logging middleware"`

**Key prefix for this category:** `voltsnip/bug22/category/logging_privacy/`

---

## Snippet Keys for This Task

{{SNIPPET_KEY_COUNT}} canonical snippet(s) identified for this task:

{{SNIPPET_KEYS_BULLETS}}

Fetch these first with `voltsnip_fetch_by_canonical_keys`.
If a key returns nothing, fall back to `voltsnip_semantic_search` using one of the queries above.

---

## Execution Contract

1. Call `voltsnip_fetch_by_canonical_keys` with the listed keys above.
2. If results are sparse, call `voltsnip_semantic_search` with a focused logging/privacy query.
3. Apply the retrieved redaction/structured-log pattern directly — adapt only field names.
4. Keep your fix minimal and localized to the stated bug target lines.
5. Emit exactly one JSON: `{"code": "<full file>", "comments": "<one-line rationale>"}`.
