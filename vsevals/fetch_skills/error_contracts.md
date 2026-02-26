# VoltSnip Fetch Skill — Error Contracts | Direct REST API Access

You are fixing an **error_contracts** bug. Use the VoltSnip REST API to fetch canonical
error-payload / status-mapping patterns **before** writing any code.

## VoltSnip API Endpoints

Base URL: `{{VOLTSNIP_BASE_URL}}`

### Fetch by canonical key
```
GET {{VOLTSNIP_BASE_URL}}/api/v1/snippets/{canonical_key}
```

### Semantic search (use if direct fetch fails)
```
POST {{VOLTSNIP_BASE_URL}}/api/v1/search/semantic
{"query": "error response contract status code mapping", "limit": 3}
```

Fallback queries for this category:
- `"consistent error payload JSON serializable"`
- `"exception handler HTTP status FastAPI"`
- `"error schema code message detail typed"`

Key prefix: `voltsnip/bug22/category/error_contracts/`

---

## Snippet Keys for This Task

{{SNIPPET_KEY_COUNT}} canonical snippet(s) identified for this task:

{{SNIPPET_KEYS_BULLETS}}

---

## Execution Contract

1. Fetch the listed keys via `GET {{VOLTSNIP_BASE_URL}}/api/v1/snippets/{key}`.
2. If a key 404s, run semantic search with one of the queries above.
3. Apply the retrieved error-schema/handler pattern — adapt field names only.
4. Keep fix minimal and localized to the stated bug target lines.
5. Emit exactly one JSON: `{"code": "<full file>", "comments": "<one-line rationale>"}`.
