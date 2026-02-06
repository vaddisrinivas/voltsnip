#!/usr/bin/env python3
"""
VoltSnip API Client - Common operations for searching, creating, and voting on snippets.
Requires: requests library (python -m pip install requests --break-system-packages)
"""

import json
import requests
import sys
from typing import Optional, List, Dict, Any
from urllib.parse import quote

BASE_URL = "https://voltsnip-api.thetechcruise.com"
DEFAULT_TIMEOUT = 10

# ============================================================================
# Search Functions
# ============================================================================

def semantic_search(query: str, k: int = 20) -> List[Dict[str, Any]]:
    """
    Search VoltSnip by intent using semantic search.
    
    Args:
        query: Natural language intent (e.g., "retry with exponential backoff")
        k: Number of results (default 20, max 100)
    
    Returns:
        List of SnippetMetaResponse objects
    """
    url = f"{BASE_URL}/api/v1/search/semantic"
    params = {"q": query, "k": min(k, 100)}
    
    try:
        resp = requests.get(url, params=params, timeout=DEFAULT_TIMEOUT)
        resp.raise_for_status()
        return resp.json()
    except requests.RequestException as e:
        print(f"❌ Search failed: {e}", file=sys.stderr)
        return []

def filtered_search(
    language: Optional[str] = None,
    tag: Optional[str] = None,
    limit: int = 50,
    offset: int = 0
) -> List[Dict[str, Any]]:
    """
    Search VoltSnip by language and/or tag with pagination.
    
    Args:
        language: Programming language (e.g., "python", "javascript")
        tag: Tag to filter by (e.g., "csv", "retry")
        limit: Results per page (default 50)
        offset: Pagination offset (default 0)
    
    Returns:
        List of SnippetMetaResponse objects
    """
    url = f"{BASE_URL}/api/v1/search/"
    params = {
        "limit": min(limit, 100),
        "offset": max(offset, 0)
    }
    if language:
        params["language"] = language
    if tag:
        params["tag"] = tag
    
    try:
        resp = requests.get(url, params=params, timeout=DEFAULT_TIMEOUT)
        resp.raise_for_status()
        return resp.json()
    except requests.RequestException as e:
        print(f"❌ Search failed: {e}", file=sys.stderr)
        return []

# ============================================================================
# Snippet CRUD
# ============================================================================

def create_snippet(
    code: str,
    title: Optional[str] = None,
    description: Optional[str] = None,
    language: Optional[str] = None,
    tags: Optional[List[str]] = None,
    kind: str = "snippet",
    canonical_key: Optional[str] = None
) -> Optional[Dict[str, Any]]:
    """
    Create a new snippet in VoltSnip.
    
    Args:
        code: Snippet code (required, max 1,000,000 chars)
        title: Human-friendly name (max 200 chars)
        description: What/when/I/O/edge cases (max 1000 chars)
        language: Programming language (max 50 chars)
        tags: List of tags (normalized lowercase, 50 chars each)
        kind: "snippet", "utility", "skill", "prompt", or "config"
        canonical_key: Stable slug for versioning (max 200 chars)
    
    Returns:
        SnippetDetailResponse on success, None on failure
    """
    if not code or len(code) > 1_000_000:
        print("❌ Code required and must be ≤ 1,000,000 chars", file=sys.stderr)
        return None
    
    payload = {"code": code}
    if title and len(title) <= 200:
        payload["title"] = title
    if description and len(description) <= 1000:
        payload["description"] = description
    if language and len(language) <= 50:
        payload["language"] = language
    if tags:
        payload["tags"] = [t[:50] for t in tags if t]
    payload["kind"] = kind
    if canonical_key and len(canonical_key) <= 200:
        payload["canonical_key"] = canonical_key
    
    url = f"{BASE_URL}/api/v1/snippets/"
    
    try:
        resp = requests.post(
            url,
            json=payload,
            headers={"Content-Type": "application/json"},
            timeout=DEFAULT_TIMEOUT
        )
        resp.raise_for_status()
        result = resp.json()
        print(f"✅ Snippet created: {result['id']}")
        return result
    except requests.RequestException as e:
        print(f"❌ Create failed: {e}", file=sys.stderr)
        if hasattr(e.response, 'json'):
            print(f"   Details: {e.response.json()}", file=sys.stderr)
        return None

def get_snippet(snippet_id: str) -> Optional[Dict[str, Any]]:
    """
    Retrieve full snippet by ID.
    
    Args:
        snippet_id: UUID of snippet
    
    Returns:
        SnippetDetailResponse (includes full code) or None
    """
    url = f"{BASE_URL}/api/v1/snippets/{snippet_id}"
    
    try:
        resp = requests.get(url, timeout=DEFAULT_TIMEOUT)
        resp.raise_for_status()
        return resp.json()
    except requests.RequestException as e:
        print(f"❌ Fetch failed: {e}", file=sys.stderr)
        return None

# ============================================================================
# Engagement (Voting & Views)
# ============================================================================

def vote_snippet(snippet_id: str, value: int = 1) -> bool:
    """
    Vote on a snippet (upvote or downvote).
    
    Args:
        snippet_id: UUID of snippet
        value: 1 for upvote, -1 for downvote
    
    Returns:
        True on success, False on failure
    """
    if value not in [1, -1]:
        print("❌ Vote value must be 1 (upvote) or -1 (downvote)", file=sys.stderr)
        return False
    
    url = f"{BASE_URL}/api/v1/snippets/{snippet_id}/vote"
    payload = {"value": value}
    
    try:
        resp = requests.post(
            url,
            json=payload,
            headers={"Content-Type": "application/json"},
            timeout=DEFAULT_TIMEOUT
        )
        resp.raise_for_status()
        action = "upvoted" if value == 1 else "downvoted"
        print(f"✅ Snippet {action}: {snippet_id}")
        return True
    except requests.RequestException as e:
        action = "upvote" if value == 1 else "downvote"
        print(f"❌ {action.capitalize()} failed: {e}", file=sys.stderr)
        return False

def track_view(snippet_id: str) -> bool:
    """
    Track a view for a snippet.
    
    Args:
        snippet_id: UUID of snippet
    
    Returns:
        True on success, False on failure
    """
    url = f"{BASE_URL}/api/v1/snippets/{snippet_id}/view"
    
    try:
        resp = requests.post(url, timeout=DEFAULT_TIMEOUT)
        resp.raise_for_status()
        print(f"✅ View tracked: {snippet_id}")
        return True
    except requests.RequestException as e:
        print(f"❌ View tracking failed: {e}", file=sys.stderr)
        return False

# ============================================================================
# Feeds (Discovery)
# ============================================================================

def get_hot_feed(limit: int = 20) -> List[Dict[str, Any]]:
    """Get hot snippets (high engagement in last 24h)."""
    url = f"{BASE_URL}/api/v1/feeds/hot"
    try:
        resp = requests.get(url, params={"limit": min(limit, 100)}, timeout=DEFAULT_TIMEOUT)
        resp.raise_for_status()
        return resp.json()
    except requests.RequestException as e:
        print(f"❌ Hot feed failed: {e}", file=sys.stderr)
        return []

def get_trending_feed(limit: int = 20) -> List[Dict[str, Any]]:
    """Get trending snippets (growing popularity in last 7d)."""
    url = f"{BASE_URL}/api/v1/feeds/trending"
    try:
        resp = requests.get(url, params={"limit": min(limit, 100)}, timeout=DEFAULT_TIMEOUT)
        resp.raise_for_status()
        return resp.json()
    except requests.RequestException as e:
        print(f"❌ Trending feed failed: {e}", file=sys.stderr)
        return []

def get_top_feed(limit: int = 20) -> List[Dict[str, Any]]:
    """Get top-rated snippets of all time."""
    url = f"{BASE_URL}/api/v1/feeds/top"
    try:
        resp = requests.get(url, params={"limit": min(limit, 100)}, timeout=DEFAULT_TIMEOUT)
        resp.raise_for_status()
        return resp.json()
    except requests.RequestException as e:
        print(f"❌ Top feed failed: {e}", file=sys.stderr)
        return []

def get_most_used_feed(limit: int = 20) -> List[Dict[str, Any]]:
    """Get most-referenced snippets."""
    url = f"{BASE_URL}/api/v1/feeds/most-used"
    try:
        resp = requests.get(url, params={"limit": min(limit, 100)}, timeout=DEFAULT_TIMEOUT)
        resp.raise_for_status()
        return resp.json()
    except requests.RequestException as e:
        print(f"❌ Most-used feed failed: {e}", file=sys.stderr)
        return []

# ============================================================================
# Display Functions
# ============================================================================

def format_snippet(snippet: Dict[str, Any], show_code: bool = False) -> str:
    """Format snippet for display."""
    lines = [
        f"🔗 {snippet.get('id', 'unknown')}",
        f"📝 {snippet.get('title', 'Untitled')}",
        f"💬 {snippet.get('description', 'No description')[:100]}...",
        f"🏷️  {', '.join(snippet.get('tags', []))}",
        f"👁️ {snippet.get('view_count', 0)} views",
        f"👍 {snippet.get('upvote_count', 0)} upvotes",
        f"👎 {snippet.get('downvote_count', 0)} downvotes",
        f"📅 Updated: {snippet.get('updated_at', 'unknown')}"
    ]
    if show_code and 'code' in snippet:
        lines.append(f"\n```{snippet.get('language', '')}\n{snippet['code'][:300]}...\n```")
    return "\n".join(lines)

# ============================================================================
# CLI (Optional usage demo)
# ============================================================================

if __name__ == "__main__":
    # Example usage
    print("🔍 Semantic search example:")
    results = semantic_search("retry with exponential backoff", k=3)
    for r in results:
        print(format_snippet(r))
        print()
    
    print("\n📚 Hot feed example:")
    hot = get_hot_feed(limit=3)
    for h in hot:
        print(f"  • {h.get('title', 'Untitled')} ({h.get('upvote_count', 0)} upvotes)")
