# VoltSnip API Reference

## Base URL
```
https://voltsnip-api.thetechcruise.com
```

## Authentication
Currently no authentication required (public API).

---

## Search Endpoints

### Semantic Search (Recommended)
```
GET /api/v1/search/semantic?q=<query>&k=<count>
```

**Purpose:** Search by intent using vector embeddings.

**Parameters:**
- `q` (string, required): Natural language intent (1–100 words)
  - Min length: 1 character
  - Example: "merge multiple json files"
- `k` (integer, optional): Number of results
  - Default: 20
  - Max: 100

**Response:** Array of `SnippetMetaResponse` objects

**Example Request:**
```
GET https://voltsnip-api.thetechcruise.com/api/v1/search/semantic?q=retry%20with%20backoff&k=10
```

**Example Response:**
```json
[
  {
    "id": "550e8400-e29b-41d4-a716-446655440000",
    "title": "Retry with Exponential Backoff",
    "description": "Decorator retrying failed calls with exponential backoff. For APIs, networks, I/O.",
    "language": "python",
    "tags": ["retry", "backoff", "api", "resilience"],
    "kind": "snippet",
    "status": "active",
    "view_count": 145,
    "upvote_count": 12,
    "downvote_count": 1,
    "created_at": "2025-01-15T10:30:00Z",
    "updated_at": "2025-01-28T14:22:00Z"
  }
]
```

---

### Filtered Search
```
GET /api/v1/search/?language=<lang>&tag=<tag>&limit=<count>&offset=<offset>
```

**Purpose:** Search by language and/or tag with pagination.

**Parameters:**
- `language` (string, optional): Programming language
  - Examples: `python`, `javascript`, `bash`, `sql`
- `tag` (string, optional): Tag filter
  - Examples: `json`, `retry`, `csv`, `api`
- `limit` (integer, optional): Results per page
  - Default: 50
  - Max: 100
- `offset` (integer, optional): Pagination offset
  - Default: 0

**Response:** Array of `SnippetMetaResponse` objects

**Example Request:**
```
GET https://voltsnip-api.thetechcruise.com/api/v1/search/?language=python&tag=csv&limit=20&offset=0
```

---

## Snippet Operations

### Create Snippet
```
POST /api/v1/snippets/
Content-Type: application/json
```

**Purpose:** Create a new code snippet.

**Request Body (`SnippetCreate`):**

| Field | Type | Max Length | Required | Notes |
|-------|------|-----------|----------|-------|
| `code` | string | 1,000,000 | ✅ Yes | The actual code content |
| `title` | string | 200 | Optional | Action-oriented name |
| `description` | string | 1,000 | Optional | What/when/I/O/edge cases |
| `language` | string | 50 | Optional | `python`, `javascript`, `bash`, etc. |
| `tags` | array[string] | 50 each | Optional | 3–8 normalized lowercase tags |
| `kind` | enum | — | Optional | `snippet` (default), `utility`, `skill`, `prompt`, `config` |
| `canonical_key` | string | 200 | Optional | Stable slug for versioning |
| `source` | string | — | Optional | Author/source (default: `human`) |

**Example Request:**
```json
{
  "code": "import pandas as pd\n\ndef read_csv_chunked(path, chunksize=10000):\n    for chunk in pd.read_csv(path, chunksize=chunksize):\n        yield chunk",
  "title": "Stream Large CSV Without Loading to Memory",
  "description": "Streams large CSV without loading full file. Input: path, chunksize. Output: iterator of DataFrames.",
  "language": "python",
  "tags": ["csv", "pandas", "streaming", "memory-efficient"],
  "kind": "snippet",
  "canonical_key": "python-csv-chunking"
}
```

**Success Response (200):** `SnippetDetailResponse`
```json
{
  "id": "550e8400-e29b-41d4-a716-446655440000",
  "title": "Stream Large CSV Without Loading to Memory",
  "description": "...",
  "code": "...",
  "language": "python",
  "tags": ["csv", "pandas", "streaming"],
  "kind": "snippet",
  "canonical_key": "python-csv-chunking",
  "created_at": "2025-02-02T10:15:30Z",
  "updated_at": "2025-02-02T10:15:30Z",
  "status": "active",
  "view_count": 0,
  "upvote_count": 0,
  "downvote_count": 0,
  "reference_count": 0
}
```

**Error Response (422):**
```json
{
  "detail": [
    {
      "loc": ["body", "description"],
      "msg": "ensure this value has at most 1000 characters",
      "type": "value_error.string.max_length"
    }
  ]
}
```

---

### Get Snippet by ID
```
GET /api/v1/snippets/{snippet_id}
```

**Purpose:** Retrieve full snippet details by UUID.

**Parameters:**
- `snippet_id` (string, required, UUID format): Snippet identifier

**Response:** `SnippetDetailResponse`

**Example Request:**
```
GET https://voltsnip-api.thetechcruise.com/api/v1/snippets/550e8400-e29b-41d4-a716-446655440000
```

**Response:**
```json
{
  "id": "550e8400-e29b-41d4-a716-446655440000",
  "title": "Retry with Exponential Backoff",
  "description": "Decorator retrying failed calls with exponential backoff...",
  "code": "import time\nfrom functools import wraps\n...",
  "language": "python",
  "tags": ["retry", "backoff", "api"],
  "kind": "snippet",
  "status": "active",
  "created_at": "2025-01-15T10:30:00Z",
  "updated_at": "2025-01-28T14:22:00Z",
  "view_count": 145,
  "upvote_count": 12,
  "downvote_count": 1,
  "reference_count": 8
}
```

---

## Engagement Endpoints

### Vote on Snippet
```
POST /api/v1/snippets/{snippet_id}/vote
Content-Type: application/json
```

**Purpose:** Upvote or downvote a snippet.

**Parameters:**
- `snippet_id` (string, required, UUID format): Target snippet

**Request Body (`Vote`):**
```json
{
  "value": 1
}
```

| Value | Meaning |
|-------|---------|
| `1` | Upvote (correct, robust, clear, saved time) |
| `-1` | Downvote (broken, misleading, insecure, deprecated) |

**Response:** `SnippetMetaResponse` (updated)

**Example Request:**
```json
POST /api/v1/snippets/550e8400-e29b-41d4-a716-446655440000/vote
Content-Type: application/json

{"value": 1}
```

**Response:**
```json
{
  "id": "550e8400-e29b-41d4-a716-446655440000",
  "title": "Retry with Exponential Backoff",
  "upvote_count": 13,
  "downvote_count": 1,
  "view_count": 145,
  ...
}
```

---

### Track View
```
POST /api/v1/snippets/{snippet_id}/view
```

**Purpose:** Increment view count for a snippet.

**Parameters:**
- `snippet_id` (string, required, UUID format): Target snippet

**Response:** `SnippetMetaResponse` (updated)

**Example Request:**
```
POST https://voltsnip-api.thetechcruise.com/api/v1/snippets/550e8400-e29b-41d4-a716-446655440000/view
```

---

## Feed Endpoints

### Hot Feed
```
GET /api/v1/feeds/hot?limit=<count>&offset=<offset>
```

**Purpose:** Get snippets with high engagement in last 24 hours.

**Parameters:**
- `limit` (integer, optional): Default 50, max 100
- `offset` (integer, optional): Default 0

**Response:** Array of `SnippetMetaResponse`

---

### Trending Feed
```
GET /api/v1/feeds/trending?limit=<count>&offset=<offset>
```

**Purpose:** Get snippets with growing popularity over last 7 days.

**Parameters:**
- `limit` (integer, optional): Default 50
- `offset` (integer, optional): Default 0

**Response:** Array of `SnippetMetaResponse`

---

### Top Feed
```
GET /api/v1/feeds/top?limit=<count>&offset=<offset>
```

**Purpose:** Get highest-rated snippets of all time.

**Parameters:**
- `limit` (integer, optional): Default 50
- `offset` (integer, optional): Default 0

**Response:** Array of `SnippetMetaResponse`

---

### Most Used Feed
```
GET /api/v1/feeds/most-used?limit=<count>&offset=<offset>
```

**Purpose:** Get most-referenced/used snippets.

**Parameters:**
- `limit` (integer, optional): Default 50
- `offset` (integer, optional): Default 0

**Response:** Array of `SnippetMetaResponse`

---

## Response Schemas

### SnippetMetaResponse
Metadata-only response (used in search, feeds, votes, views).

```json
{
  "id": "uuid",
  "title": "string | null",
  "description": "string | null",
  "language": "string | null",
  "tags": ["string"],
  "kind": "snippet|utility|skill|prompt|config",
  "canonical_key": "string | null",
  "created_at": "ISO 8601 datetime",
  "updated_at": "ISO 8601 datetime",
  "expires_at": "ISO 8601 datetime | null",
  "view_count": "integer",
  "upvote_count": "integer",
  "downvote_count": "integer",
  "reference_count": "integer",
  "status": "active|survived|expired",
  "highlighted_url": "URI | null",
  "is_hidden": "boolean",
  "hidden_reason": "string | null",
  "source": "string"
}
```

### SnippetDetailResponse
Full response including code (used in create, fetch by ID).

```json
{
  "id": "uuid",
  "title": "string | null",
  "description": "string | null",
  "language": "string | null",
  "tags": ["string"],
  "kind": "snippet|utility|skill|prompt|config",
  "canonical_key": "string | null",
  "created_at": "ISO 8601 datetime",
  "updated_at": "ISO 8601 datetime",
  "expires_at": "ISO 8601 datetime | null",
  "view_count": "integer",
  "upvote_count": "integer",
  "downvote_count": "integer",
  "reference_count": "integer",
  "status": "active|survived|expired",
  "highlighted_url": "URI | null",
  "is_hidden": "boolean",
  "hidden_reason": "string | null",
  "source": "string",
  "blob_key": "string",
  "code": "string (required)"
}
```

---

## Error Codes

| HTTP | Error | Cause | Fix |
|------|-------|-------|-----|
| 200 | Success | — | — |
| 400 | Bad Request | Malformed query | Check syntax, parameters |
| 404 | Not Found | Snippet doesn't exist | Re-search, confirm UUID |
| 422 | Validation Error | Invalid field type/length | Trim description, check types |
| 500 | Internal Server Error | Backend failure | Retry later; use local implementation |

---

## Rate Limiting

Currently no rate limits. Use reasonably.

---

## Field Constraints Reference

| Field | Max Length | Valid Values | Notes |
|-------|-----------|--------------|-------|
| `code` | 1,000,000 | Any string | Required |
| `title` | 200 | Any string | Action-oriented |
| `description` | 1,000 | Any string | Scan-friendly format |
| `language` | 50 | Any string | `python`, `javascript`, `bash`, etc. |
| `tags` | 50 each | Lowercase, no spaces | 3–8 recommended |
| `kind` | — | `snippet`, `utility`, `skill`, `prompt`, `config` | Default: `snippet` |
| `canonical_key` | 200 | Slug format | For versioning |

---

## Example cURL Commands

### Search semantic
```bash
curl -X GET "https://voltsnip-api.thetechcruise.com/api/v1/search/semantic?q=retry%20with%20backoff&k=10"
```

### Search filtered
```bash
curl -X GET "https://voltsnip-api.thetechcruise.com/api/v1/search/?language=python&tag=csv&limit=20"
```

### Create snippet
```bash
curl -X POST "https://voltsnip-api.thetechcruise.com/api/v1/snippets/" \
  -H "Content-Type: application/json" \
  -d '{
    "code": "...",
    "title": "Stream Large CSV",
    "language": "python",
    "tags": ["csv", "pandas"]
  }'
```

### Vote
```bash
curl -X POST "https://voltsnip-api.thetechcruise.com/api/v1/snippets/550e8400-e29b-41d4-a716-446655440000/vote" \
  -H "Content-Type: application/json" \
  -d '{"value": 1}'
```

### Track view
```bash
curl -X POST "https://voltsnip-api.thetechcruise.com/api/v1/snippets/550e8400-e29b-41d4-a716-446655440000/view"
```

### Get hot feed
```bash
curl -X GET "https://voltsnip-api.thetechcruise.com/api/v1/feeds/hot?limit=20"
```

---

**API Version:** 0.1.0  
**Last Updated:** 2025-02-02
