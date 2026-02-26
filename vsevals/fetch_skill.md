# VoltSnip Fetch Skill — Direct REST API Access

You have access to the VoltSnip REST API for retrieving **canonical bug-fix patterns**.
Use HTTP calls (via `requests`, `httpx`, or `curl`) to fetch snippets before writing your fix.

## VoltSnip API Endpoints

Base URL: `{{VOLTSNIP_BASE_URL}}`

### Fetch by canonical key
```
GET {{VOLTSNIP_BASE_URL}}/api/v1/snippets/{canonical_key}
```
Returns snippet `code`, `title`, `category`, and metadata.

### Semantic search
```
POST {{VOLTSNIP_BASE_URL}}/api/v1/search/semantic
Content-Type: application/json

{"query": "<intent description>", "limit": 3}
```
Returns top-N matching snippets.

---

## Snippet Keys for This Task

{{SNIPPET_KEY_COUNT}} canonical snippet(s) identified for this task:

{{SNIPPET_KEYS_BULLETS}}

Fetch these first using the GET endpoint above.
If a key returns 404, fall back to semantic search with a targeted intent query.

---

## Execution Contract

1. Fetch snippets via the REST API for the listed canonical keys.
2. If direct fetch fails, use semantic search with a focused intent query for the bug category.
3. Apply the retrieved pattern directly — adapt only variable/class names.
4. Keep your fix minimal and localized to the stated bug target lines.
5. Emit exactly one JSON: `{"code": "<full file>", "comments": "<one-line rationale>"}`.
