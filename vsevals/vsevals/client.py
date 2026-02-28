"""VoltSnip HTTP client.

Thin wrapper around the VoltSnip REST API (httpx, with retry).

Usage:
    client = VoltSnipClient(base_url="http://localhost:8011")
    snippets = client.get_by_canonical_keys(["voltsnip/bug22/..."], limit=6, max_chars=1200)
    snippets = client.semantic_search(q="retry policy", k=4, max_chars=1200)
"""

from __future__ import annotations

import logging
import time
from typing import Any, Callable, TypeVar

import httpx

from vsevals.models import RetrievedSnippet

LOGGER = logging.getLogger(__name__)
_T = TypeVar("_T")


class VoltSnipClient:
    def __init__(
        self,
        *,
        base_url: str,
        timeout_seconds: int = 20,
        retry_attempts: int = 3,
        retry_backoff_seconds: float = 0.35,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds
        self.retry_attempts = max(1, retry_attempts)
        self.retry_backoff_seconds = max(0.0, retry_backoff_seconds)
        # Per-client counters (run_one builds a fresh client per run).
        self.retry_count_total = 0
        self.rate_limit_error_count = 0
        self.timeout_error_count = 0
        self.error_count_total = 0

    def preflight_check(self) -> bool:
        """Return True if server is reachable (only checked for localhost)."""
        if "localhost" not in self.base_url and "127.0.0.1" not in self.base_url:
            return True
        try:
            with httpx.Client(timeout=self.timeout_seconds) as c:
                c.get(f"{self.base_url}/health").raise_for_status()
            LOGGER.debug("voltsnip preflight ok base_url=%s", self.base_url)
            return True
        except Exception:
            LOGGER.debug("voltsnip preflight failed base_url=%s", self.base_url, exc_info=True)
            return False

    def get_by_canonical_keys(
        self,
        canonical_keys: list[str],
        *,
        limit: int,
        max_chars: int,
    ) -> list[RetrievedSnippet]:
        """Fetch snippets matching the given canonical keys (exact lookup)."""
        keys = [k for k in canonical_keys if k][:limit]
        if not keys:
            return []

        wanted = set(keys)
        found: dict[str, dict[str, Any]] = {}

        # Fetch individually by ID/slug instead of relying on bulk query parameters
        import httpx
        for key in wanted:
            if key in found:
                continue
            try:
                detail = self._call("GET", f"/api/v1/snippets/by-key/{key}")
                if isinstance(detail, dict):
                    found[key] = detail
            except httpx.HTTPError:
                LOGGER.debug("Snippet %s not found remotely", key)
            except Exception as e:
                LOGGER.warning("Error fetching snippet %s: %s", key, e)

        return [_to_snippet(found[k], max_chars) for k in keys if k in found]

    def semantic_search(self, *, q: str, k: int, max_chars: int) -> list[RetrievedSnippet]:
        """Run semantic search and return up to k snippets."""
        if not q.strip():
            return []
        meta_rows = self._call("GET", "/api/v1/search/semantic", query={"q": q, "k": str(k)})
        if not isinstance(meta_rows, list):
            return []
        details: list[dict[str, Any]] = []
        for meta in meta_rows:
            if not isinstance(meta, dict):
                continue
            sid = _str(meta.get("id"))
            if not sid:
                continue
            detail = self._call("GET", f"/api/v1/snippets/{sid}")
            if isinstance(detail, dict):
                details.append(detail)
        return [_to_snippet(d, max_chars) for d in details]

    # -------------------------------------------------------------------------

    def _call(
        self,
        method: str,
        path: str,
        *,
        query: dict[str, str] | None = None,
        body: dict[str, Any] | None = None,
    ) -> Any:
        return self._with_retry(path, lambda: self._http(method, path, query=query, body=body))

    def _http(self, method: str, path: str, *, query: dict | None = None, body: dict | None = None) -> Any:
        url = f"{self.base_url}{path}"
        with httpx.Client(timeout=self.timeout_seconds) as c:
            r = c.request(method, url, params=query, json=body)
        r.raise_for_status()
        return r.json()

    def _with_retry(self, label: str, fn: Callable[[], _T]) -> _T:
        for attempt in range(1, self.retry_attempts + 1):
            try:
                return fn()
            except Exception as exc:
                self.error_count_total += 1
                if _is_rate_limit_error(exc):
                    self.rate_limit_error_count += 1
                if _is_timeout_error(exc):
                    self.timeout_error_count += 1
                if attempt >= self.retry_attempts:
                    raise
                self.retry_count_total += 1
                delay = self.retry_backoff_seconds * (2 ** (attempt - 1))
                LOGGER.warning("voltsnip retry op=%s attempt=%d/%d delay=%.2fs err=%s", label, attempt, self.retry_attempts, delay, exc)
                if delay > 0:
                    time.sleep(delay)
        raise RuntimeError("unreachable")  # pragma: no cover


# --- Helpers -----------------------------------------------------------------


def _to_snippet(detail: dict[str, Any], max_chars: int) -> RetrievedSnippet:
    return RetrievedSnippet(
        id=_str(detail.get("id")) or "unknown",
        canonical_key=_str(detail.get("canonical_key")),
        title=_str(detail.get("title")) or "",
        language=_str(detail.get("language")),
        tags=[str(t) for t in detail.get("tags", []) if isinstance(t, str)],
        description=_str(detail.get("description")),
        code=(_str(detail.get("code")) or "")[:max_chars],
    )


def _str(v: object) -> str | None:
    return str(v) if v is not None else None


def _is_rate_limit_error(exc: Exception) -> bool:
    if isinstance(exc, httpx.HTTPStatusError):
        try:
            if exc.response is not None and exc.response.status_code == 429:
                return True
        except Exception:
            pass
    msg = str(exc).lower()
    return any(t in msg for t in ("rate limit", "ratelimit", "too many requests", "quota", "429"))


def _is_timeout_error(exc: Exception) -> bool:
    if isinstance(exc, (httpx.TimeoutException, TimeoutError)):
        return True
    msg = str(exc).lower()
    return "timeout" in msg or "timed out" in msg
