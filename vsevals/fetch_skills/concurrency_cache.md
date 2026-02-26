# VoltSnip Fetch Skill — Concurrency & Cache | Direct REST API Access

You are fixing a **concurrency_cache** bug. Use the VoltSnip REST API to fetch canonical
stampede-prevention / TTL / task-local isolation patterns **before** writing any code.

## VoltSnip API Endpoints

Base URL: `{{VOLTSNIP_BASE_URL}}`

### Fetch by canonical key
```
GET {{VOLTSNIP_BASE_URL}}/api/v1/snippets/{canonical_key}
```

### Semantic search (use if direct fetch fails)
```
POST {{VOLTSNIP_BASE_URL}}/api/v1/search/semantic
{"query": "cache TTL stampede coalesce task local context", "limit": 3}
```

Fallback queries for this category:
- `"asyncio lock per key single flight"`
- `"ContextVar task local thread isolation"`
- `"stale while revalidate negative cache TTL"`

Key prefix: `voltsnip/bug22/category/concurrency_cache/`

---

## Snippet Keys for This Task

{{SNIPPET_KEY_COUNT}} canonical snippet(s) identified for this task:

{{SNIPPET_KEYS_BULLETS}}

---

## Execution Contract

1. Fetch the listed keys via `GET {{VOLTSNIP_BASE_URL}}/api/v1/snippets/{key}`.
2. If a key 404s, run semantic search with one of the queries above.
3. Apply the retrieved coalescing/TTL pattern — adapt variable names only.
4. Keep fix minimal and localized to the stated bug target lines.
5. Emit exactly one JSON: `{"code": "<full file>", "comments": "<one-line rationale>"}`.
