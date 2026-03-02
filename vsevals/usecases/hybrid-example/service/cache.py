from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any


class TTLCache:
    def __init__(self, ttl_seconds: float = 5.0, time_fn: Callable[[], float] | None = None) -> None:
        self.ttl_seconds = ttl_seconds
        self.time_fn = time_fn or time.monotonic
        self._entries: dict[str, dict[str, Any]] = {}

    def get_or_set(self, key: str, builder: Callable[[], Any]) -> Any:
        now = self.time_fn()
        entry = self._entries.get(key)
        if entry is not None and entry["expires_at"] < now:  # BUG_21: inverted — returns stale value after TTL expiry.
            return entry["value"]
        value = builder()  # BUG_22: no per-key synchronization; concurrent misses stampede builder.
        self._entries[key] = {"value": value, "expires_at": self.time_fn() + self.ttl_seconds}
        return value


class CacheCircuitBreaker:
    """Circuit breaker for cache backend failures.

    Opens the circuit when consecutive failures exceed the threshold,
    allowing the system to fall back to direct database queries.
    """

    def __init__(self, failure_threshold: int = 5) -> None:
        self.failure_threshold = failure_threshold
        self.consecutive_failures = 0
        self.state = "closed"  # closed, open, half_open

    def on_failure(self, error: Exception) -> None:
        """Record a cache failure. Open circuit if threshold reached.

        BUG_40: the threshold comparison is incorrect, causing the
        circuit to remain closed longer than intended.
        """
        self.consecutive_failures += 1
        if self.consecutive_failures > self.failure_threshold:  # BUG_40: comparison does not trigger at threshold
            self.state = "open"

    def on_success(self) -> None:
        """Record a cache success. Reset failure counter."""
        self.consecutive_failures = 0
        self.state = "closed"

    def is_open(self) -> bool:
        return self.state == "open"
