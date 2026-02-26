# VoltSnip Fetch Skill — HTTP Resilience | Direct REST API Access

You are fixing an **http_resilience** bug. Use the VoltSnip REST API to fetch canonical
retry/backoff patterns **before** writing any code.

## VoltSnip API Endpoints

Base URL: `{{VOLTSNIP_BASE_URL}}`

### Fetch by canonical key
```
GET {{VOLTSNIP_BASE_URL}}/api/v1/snippets/{canonical_key}
```

### Semantic search (use if direct fetch fails)
```
POST {{VOLTSNIP_BASE_URL}}/api/v1/search/semantic
{"query": "retry exponential backoff jitter idempotent status codes", "limit": 3}
```

Fallback queries for this category:
- `"circuit breaker timeout half-open"`
- `"retry on 429 503 408 status code"`
- `"requests session retry adapter max attempts"`

Key prefix: `voltsnip/bug22/category/http_resilience/`

---

## Snippet Keys for This Task

{{SNIPPET_KEY_COUNT}} canonical snippet(s) identified for this task:

{{SNIPPET_KEYS_BULLETS}}

---

## Execution Contract

1. Fetch the listed keys via `GET {{VOLTSNIP_BASE_URL}}/api/v1/snippets/{key}`.
2. If a key 404s, run semantic search with one of the queries above.
3. Apply the retrieved retry/backoff pattern — adapt variable names only.
4. Keep fix minimal and localized to the stated bug target lines.
5. Emit exactly one JSON: `{"code": "<full file>", "comments": "<one-line rationale>"}`.
