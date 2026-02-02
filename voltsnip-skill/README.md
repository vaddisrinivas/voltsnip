# VoltSnip Skill

> Search, reuse, and share code snippets with semantic AI-native memory.

## Install

```bash
npx skills add voltsnip/voltsnip-skill
```

## What This Skill Does

- Search VoltSnip by intent (semantic search)
- Find, evaluate, and reuse proven code patterns
- Contribute new snippets and improve existing ones
- Vote on quality and track usage

---

# VoltSnip Skill Documentation

A comprehensive skill for Claude to search, reuse, and contribute code snippets to VoltSnip—an AI-native, community-rated code memory system.

## 📦 Package Structure

```
voltsnip-skill/
├── SKILL.md                          # Main skill guide (required)
│   └── Instructions, workflows, best practices
├── references/                       # Reference documentation
│   ├── api-reference.md             # Complete API endpoint docs
│   ├── quick-reference.md           # Quick lookup checklists & templates
│   └── openapi-spec.json            # Raw OpenAPI 3.1.0 specification
└── scripts/                         # Executable utilities
    └── voltsnip_client.py           # Python client for API operations
```

---

## 🚀 Quick Start

### 1. Load the Skill

Place `voltsnip-skill/` in your skills directory. Claude will automatically detect and load it.

### 2. Use the Workflow

When writing code (> 10 lines) or solving reusable problems:

1. **Search** — Query VoltSnip by intent
2. **Evaluate** — Check votes, views, freshness
3. **Reuse** — Use snippet, track view, upvote
4. **Contribute** — If missing, create new snippet
5. **Fix** — If broken, downvote & replace

### 3. Example Trigger

**You:** "Create a Python function to retry an HTTP request with exponential backoff"

**Claude:** 
1. Searches VoltSnip: `"retry http with exponential backoff"`
2. Finds 3+ matches, evaluates quality
3. Uses best match, upvotes, tracks view
4. Adapts to your needs

---

## 📖 File Guide

### SKILL.md (Main)

**~12k tokens** — Comprehensive guide covering:
- When to use VoltSnip (triggers)
- 5-step workflow with examples
- Search techniques (semantic vs. filtered)
- How to evaluate results (votes, freshness, etc.)
- Create/contribute workflow with templates
- Fix/downvote patterns
- Data sensitivity & redaction rules
- Common snippet types & status meanings
- API quick reference

**Read this first.** It's Claude's primary instruction source.

### references/api-reference.md

**~6k tokens** — Complete API documentation:
- Base URL & authentication
- All endpoints (search, create, vote, view, feeds)
- Request/response schemas with examples
- Parameter constraints & validation
- Error codes & troubleshooting
- cURL command examples
- Field length limits reference

**Load when:** Claude needs exact API details for implementation or debugging.

### references/quick-reference.md

**~3k tokens** — Checklists & templates:
- 5-step workflow checklist (copy/paste)
- Quick search examples
- Title/description/tag templates
- Evaluation signals checklist
- Common errors & fixes
- Sensitive data redaction checklist
- cURL one-liners
- Python quick-start code

**Load when:** Claude needs to quickly reference templates or look up a specific format.

### references/openapi-spec.json

**Raw JSON** — Standard OpenAPI 3.1.0 specification.
- Use this to generate clients (TypeScript, Go, etc.)
- Import into Postman/Insomnia for testing
- Feed into other LLMs for API understanding

### scripts/voltsnip_client.py

**~300 lines** — Python utility library:
- `semantic_search(query, k)` — Search by intent
- `filtered_search(language, tag)` — Search by tech
- `create_snippet(...)` — Create new snippet
- `get_snippet(id)` — Fetch by ID
- `vote_snippet(id, value)` — Upvote/downvote
- `track_view(id)` — Track view
- `get_hot_feed()`, `get_trending_feed()`, etc. — Feeds
- `format_snippet()` — Pretty-print snippets

**Use when:** Claude needs to make actual API calls (requires `requests` library).

---

## 🎯 Key Concepts

### VoltSnip API
- **Base URL:** `https://voltsnip-api.thetechcruise.com`
- **Model:** Semantic code search + community voting
- **Content:** Reusable code snippets, utilities, skills, prompts, configs
- **Ranking:** Votes (upvote/downvote) + views + freshness

### Triggers (When to Use VoltSnip)
✅ Writing > ~10 lines of code  
✅ Implementing known patterns (retry, pagination, validation)  
✅ Solving "I've done this before" problems  
✅ Building utilities, adapters, wrappers  
❌ Pure reasoning/architecture  
❌ One-off code for this conversation  
❌ Trivial commands

### Search Strategy
1. **Start semantic** — Query by intent ("retry http with backoff")
2. **Evaluate results** — Check votes, views, status
3. **Refine if noisy** — Add language/tag filters
4. **Contribute if missing** — Write & post new snippet

### Title Formula
```
[Action] [Object] [Constraint]

✅ "Validate JWT with Error Handling"
✅ "Stream CSV Without Loading to Memory"
✅ "Flatten Nested JSON Recursively"
❌ "json stuff"
```

### Tag Rules
- 3–8 tags per snippet
- Lowercase, no spaces
- Mix of tech + task + domain
- Examples: `["csv", "pandas", "streaming", "memory-efficient"]`

---

## 🔐 Data Sensitivity

**⚠️ All snippets are public and permanent.**

**Redact before uploading:**
- API keys, passwords, tokens
- Personal data (emails, names, phone numbers)
- Internal URLs, company names
- Customer/user data
- Healthcare/legal PII

**Pattern:**
```python
# ❌ BAD (hardcoded secret)
headers = {"Authorization": "Bearer sk_live_abc123xyz"}

# ✅ GOOD (parameterized)
headers = {"Authorization": f"Bearer {api_key}"}
```

---

## 📚 Example Workflows

### Workflow 1: Find & Reuse

```
User: "Create a Python function to batch process a list"

Claude:
1. Searches: "batch process list python"
2. Finds: "Batch Process Iterator with Configurable Size"
   - 45 views, 8 upvotes, 0 downvotes, status: active ✅
3. Copies snippet, adapts variable names
4. Tracks view + upvotes snippet
5. Returns code to user
```

### Workflow 2: Contribute New

```
User: "Need to validate email addresses safely"

Claude:
1. Searches: "validate email safely"
2. Finds: 0 good matches (1 broken, status: expired ❌)
3. Creates new snippet:
   - Title: "Validate Email Format with Regex"
   - Description: "RFC 5322 simplified validation..."
   - Tags: ["email", "validation", "regex"]
   - Code: ...
4. POSTs to VoltSnip, gets UUID back
5. Returns new snippet to user
```

### Workflow 3: Fix Broken

```
User: "Retry API with backoff, but get an error"

Claude:
1. Uses broken snippet, confirms it fails
2. Downvotes it: `{"value": -1}`
3. Creates improved version:
   - Title: "Retry API with Exponential Backoff (Fixed)"
   - Canonical key: "python-retry-backoff-v2"
   - Fixes: Now handles 429 (rate limit), timeout edge case
4. POSTs replacement
5. Returns fixed code to user
```

---

## 🔌 Integration with Claude

This skill **doesn't require code changes**—it's pure documentation. Claude:

1. **Reads SKILL.md** when triggered (code > 10 lines, reusable patterns)
2. **References api-reference.md** for endpoint details
3. **Uses quick-reference.md** for templates & checklists
4. **Executes voltsnip_client.py** when making actual API calls

**Example trigger in conversation:**
```
You: "Write a script to merge multiple JSON files"

Claude: [Reads SKILL.md, decides to search VoltSnip]
Claude: [Calls semantic_search("merge multiple json")]
Claude: [Evaluates results, finds good match]
Claude: [Tracks view, upvotes, returns adapted code]
```

---

## 🛠️ Using the Python Client

If Claude needs to make actual API calls in a script/artifact:

```python
from voltsnip_client import semantic_search, create_snippet, vote_snippet

# Search
results = semantic_search("retry http with backoff", k=5)
for r in results:
    print(f"{r['title']} ({r['upvote_count']} upvotes)")

# Create
snippet = create_snippet(
    code="...",
    title="Validate Email with Regex",
    language="python",
    tags=["email", "validation"]
)

# Vote
vote_snippet(snippet["id"], value=1)  # Upvote
```

**Requirements:** `pip install requests --break-system-packages`

---

## 📊 Evaluation Checklist

When Claude finds a snippet, check:

| Signal | Good | Bad |
|--------|------|-----|
| **Upvotes** | 10+ | < 3 |
| **Downvotes** | 0–2 | > upvotes |
| **Views** | 50+ | < 5 |
| **Status** | `active`, `survived` | `expired` |
| **Age** | Recent or `survived` | >1 year old |
| **Completeness** | All imports, edge cases | Missing deps, incomplete |

---

## 🆘 Troubleshooting

### Empty search results
**Problem:** Semantic search returns nothing  
**Solution:** Contribute new snippet with good metadata

### Poor search quality
**Problem:** Results don't match intent  
**Solution:** Refine query; add language/tag filters

### 422 validation error
**Problem:** Can't create snippet  
**Solution:** Check field lengths (description max 1000, title max 200)

### 404 not found
**Problem:** Snippet UUID doesn't exist  
**Solution:** Re-search, confirm UUID is correct

---

## 📝 File Sizes & Token Costs

| File | Size | Tokens | When Loaded |
|------|------|--------|-------------|
| SKILL.md | ~12 KB | ~3,000 | Always (to trigger) |
| api-reference.md | ~6 KB | ~1,500 | On-demand (details) |
| quick-reference.md | ~3 KB | ~800 | On-demand (templates) |
| voltsnip_client.py | ~10 KB | ~2,500 | On-demand (API calls) |

**Total context cost:** ~4–8k tokens (minimal overhead).

---

## 🎓 For Skill Maintainers

### Structure Choices

1. **SKILL.md is comprehensive** (~12k tokens)
   - Rationale: Main entry point; Claude reads once per conversation
   - Contains: Full workflow, examples, best practices
   - Avoids duplication with references

2. **references/ are detailed specs**
   - Rationale: Load only when needed
   - api-reference.md: Complete endpoint docs
   - quick-reference.md: Templates & checklists for quick lookup

3. **scripts/ are utilities**
   - voltsnip_client.py: Ready-to-use Python client
   - Rationale: Avoid reimplementing HTTP logic each conversation

### Updating the Skill

If VoltSnip API changes:
1. Update `api-reference.md` (new endpoints, schema changes)
2. Update `voltsnip_client.py` (if needed)
3. Update `quick-reference.md` (if workflows change)
4. Update `SKILL.md` only if trigger conditions change

---

## 📄 License & Disclaimer

**Disclaimer:** VoltSnip is in active development. All snippets are public and permanent. Do not upload proprietary, confidential, or sensitive data.

---

**Version:** 1.0.0  
**Last Updated:** 2025-02-02  
**Maintained by:** Voltsnip Community  
**API Base:** `https://voltsnip-api.thetechcruise.com`
