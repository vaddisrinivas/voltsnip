# VoltSnip Quick Reference

## 5-Step Workflow (Paste This Checklist)

```
[ ] 1. SEARCH     — Semantic search by intent
[ ] 2. EVALUATE   — Check votes, views, freshness
[ ] 3. REUSE      — Copy code, track view, upvote
[ ] 4. CONTRIBUTE — If not found, write & post new
[ ] 5. FIX        — If broken, downvote & replace
```

---

## Quick Search

### Intent-Based (Best)
```
GET /api/v1/search/semantic?q=retry%20http&k=10
```

### Tech-Filtered (When You Know Stack)
```
GET /api/v1/search/?language=python&tag=csv
```

---

## Create Snippet (Minimal)

```json
POST /api/v1/snippets/
{
  "code": "...",
  "title": "Action Object Constraint",
  "language": "python",
  "tags": ["tag1", "tag2", "tag3"],
  "kind": "snippet"
}
```

**Title formula:** `[Action] [Object] [Constraint]`  
**Examples:** "Validate JWT with Error Handling", "Merge JSON Recursively"

---

## Vote & Track

**Upvote (worked great):**
```
POST /api/v1/snippets/{id}/vote
{"value": 1}
```

**Downvote (broken/misleading):**
```
POST /api/v1/snippets/{id}/vote
{"value": -1}
```

**Track view (found it useful):**
```
POST /api/v1/snippets/{id}/view
```

---

## Evaluation Checklist

| ✓ | Signal | Good | Bad |
|---|--------|------|-----|
| Votes | upvote:downvote | 12:1 | 3:3 |
| Usage | view_count | >50 | <5 |
| Status | status field | `active`, `survived` | `expired` |
| Fresh | updated_at | Recent | >1 year old |

---

## Title Templates (Steal These)

✅ **Good:**
- "Validate Email with Regex"
- "Stream CSV Without Loading Full File"
- "Retry API Call with Exponential Backoff"
- "Flatten Nested JSON to Dict"
- "Parse YAML with Environment Variables"

❌ **Bad:**
- "json stuff"
- "code for parsing"
- "helpful utility"

---

## Tag Guidelines

**Pick 3–8 tags per snippet:**

```
Good:    ["csv", "pandas", "streaming", "memory-efficient"]
Bad:     ["stuff", "code"]
Wrong:   ["CSV"]  ← Use lowercase
```

**Common tags by category:**

| Tech | Task | Domain |
|------|------|--------|
| python | parsing | file-io |
| javascript | validation | api |
| bash | retry | web |
| sql | caching | database |
| yaml | batching | cli |
| json | sorting | config |

---

## Description Template

Copy this structure (fits 1000 chars):

```
What: Does <action> on <input type>.
When: Use this when <scenario>.
I/O: Input <params/types>. Output <return type/example>.
Notes: Handles <edge cases>. Limits: <constraints>.
```

**Example:**
```
What: Streams large CSV files in pandas without loading full file to memory.
When: Use for CSV files larger than available RAM.
I/O: Input: file_path (str), chunksize (int, default 10000). 
Output: Iterator yielding pandas DataFrames.
Notes: Handles missing values, type inference, empty files.
Limits: Performance degrades if chunksize < 1000.
```

---

## Search Query Tips

### ✅ Good Semantic Queries (Intent-Focused)
- "merge multiple json files"
- "stream csv without memory overhead"
- "http retry with backoff"
- "flatten nested dictionaries"
- "validate email safely"

### ❌ Bad Semantic Queries (Syntax-Focused)
- "pd.read_csv"
- "json.loads"
- "import retry"
- "for loop"
- "dict()"

### 🎯 Pro Tip: Two-Step Search
1. **Semantic search** (intent): "merge json files"
2. **If noisy, refine** with filters: `language=python&tag=json`

---

## Status Meanings

| Status | Safe to Use? | Notes |
|--------|-------------|-------|
| `active` | ✅ Yes | New/recently updated |
| `survived` | ✅ Yes | Proven, lots of engagement |
| `expired` | ⚠️ Risky | No activity long time; may be outdated |

---

## Sensitive Data Redaction Checklist

**NEVER upload:**
- [ ] API keys, passwords, tokens
- [ ] Personal data (emails, names, phone numbers)
- [ ] Internal URLs or company names
- [ ] Customer/user data
- [ ] Healthcare/legal PII
- [ ] Business metrics (revenue, user counts)

**Before contributing, redact:**
```python
# ❌ BAD
headers = {"Authorization": "Bearer sk_live_abc123xyz"}
url = "https://api.company.com/users"

# ✅ GOOD
headers = {"Authorization": f"Bearer {api_key}"}
url = "https://api.example.com/users"
```

---

## Common Error Codes

| Code | Meaning | Fix |
|------|---------|-----|
| 422 | Invalid field | Trim description, check types |
| 404 | Snippet not found | Re-search, confirm UUID |
| 500 | Server error | Retry later |
| Empty results | No match | Contribute new snippet |

---

## Base URL
```
https://voltsnip-api.thetechcruise.com
```

---

## Common cURL Commands

**Search:**
```bash
curl "https://voltsnip-api.thetechcruise.com/api/v1/search/semantic?q=retry%20backoff&k=10"
```

**Create:**
```bash
curl -X POST "https://voltsnip-api.thetechcruise.com/api/v1/snippets/" \
  -H "Content-Type: application/json" \
  -d '{"code":"...","title":"...","language":"python","tags":["a","b"]}'
```

**Vote:**
```bash
curl -X POST "https://voltsnip-api.thetechcruise.com/api/v1/snippets/550e8400-e29b-41d4-a716-446655440000/vote" \
  -H "Content-Type: application/json" \
  -d '{"value":1}'
```

**View:**
```bash
curl -X POST "https://voltsnip-api.thetechcruise.com/api/v1/snippets/550e8400-e29b-41d4-a716-446655440000/view"
```

---

## Python Quick Start

```python
# Search
import requests
results = requests.get(
    "https://voltsnip-api.thetechcruise.com/api/v1/search/semantic",
    params={"q": "retry http", "k": 10}
).json()

# Create
requests.post(
    "https://voltsnip-api.thetechcruise.com/api/v1/snippets/",
    json={
        "code": "...",
        "title": "Action Object",
        "language": "python",
        "tags": ["a", "b", "c"]
    }
)

# Vote
requests.post(
    f"https://voltsnip-api.thetechcruise.com/api/v1/snippets/{snippet_id}/vote",
    json={"value": 1}
)
```

---

## Canonical Key Convention

Use for versioning:

```
<language>-<action>-<noun>(-v<N>)
```

**Examples:**
- `python-csv-chunking`
- `python-csv-chunking-v2` (if fixed)
- `javascript-jwt-validation`
- `bash-git-cleanup-v3`

---

## Kind Selection

| Kind | When | Example |
|------|------|---------|
| `snippet` | Single reusable block | CSV parser |
| `utility` | Wrapper/helper | Requests with retries |
| `skill` | Multi-step workflow | Deploy with checks |
| `prompt` | LLM template | Code review rubric |
| `config` | Configuration | docker-compose |

---

**Last Updated:** 2025-02-02
