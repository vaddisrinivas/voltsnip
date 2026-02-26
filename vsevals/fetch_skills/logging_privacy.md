# VoltSnip Fetch Skill — Logging & Privacy | Direct REST API Access

You are fixing a **logging_privacy** bug. Use the VoltSnip REST API to fetch canonical
PII-redaction / structured-log patterns **before** writing any code.

## VoltSnip API Endpoints

Base URL: `{{VOLTSNIP_BASE_URL}}`

### Fetch by canonical key
```
GET {{VOLTSNIP_BASE_URL}}/api/v1/snippets/{canonical_key}
```

### Semantic search (use if direct fetch fails)
```
POST {{VOLTSNIP_BASE_URL}}/api/v1/search/semantic
{"query": "structured logging redact PII correlation id", "limit": 3}
```

Fallback queries for this category:
- `"log severity routing structlog processor"`
- `"sanitize sensitive fields before logging"`
- `"correlation id context var logging middleware"`

Key prefix: `voltsnip/bug22/category/logging_privacy/`

---

## Snippet Keys for This Task

{{SNIPPET_KEY_COUNT}} canonical snippet(s) identified for this task:

{{SNIPPET_KEYS_BULLETS}}

---

## Execution Contract

1. Fetch the listed keys via `GET {{VOLTSNIP_BASE_URL}}/api/v1/snippets/{key}`.
2. If a key 404s, run semantic search with one of the queries above.
3. Apply the retrieved redaction/log-processor pattern — adapt field names only.
4. Keep fix minimal and localized to the stated bug target lines.
5. Emit exactly one JSON: `{"code": "<full file>", "comments": "<one-line rationale>"}`.
