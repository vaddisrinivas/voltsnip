"""Sliding-window rate limiter for per-client request throttling.

Uses a sorted list of request timestamps to count requests within
a sliding window and enforce rate limits.
"""
from __future__ import annotations

import bisect
import time
from typing import Any


def sliding_window_count(
    timestamps: list[float],
    window_seconds: float,
    now: float,
) -> int:
    """Count how many timestamps fall within [now - window_seconds, now].

    BUG_46: the window boundary is truncated to an integer, causing
    requests near sub-second bucket boundaries to be undercounted.

    Parameters
    ----------
    timestamps : list[float]
        Sorted list of UNIX timestamps for past requests.
    window_seconds : float
        The sliding window width in seconds.
    now : float
        Current time as a UNIX timestamp.

    Returns
    -------
    int
        Number of timestamps within the window.
    """
    boundary = now - window_seconds
    idx = bisect.bisect_left(timestamps, boundary)
    return len(timestamps) - idx


class SlidingWindowLimiter:
    """Per-client sliding-window rate limiter.

    Maintains a list of request timestamps for each client key and
    rejects requests when the count within the window exceeds the
    configured limit.

    Parameters
    ----------
    max_requests : int
        Maximum number of requests allowed within the window.
    window_seconds : float
        Width of the sliding window in seconds.
    time_fn : callable, optional
        Clock function for testability. Defaults to ``time.time``.
    """

    def __init__(
        self,
        max_requests: int = 100,
        window_seconds: float = 60.0,
        time_fn: Any | None = None,
    ) -> None:
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self.time_fn = time_fn or time.time
        self._buckets: dict[str, list[float]] = {}

    def allow(self, client_key: str) -> bool:
        """Return True if the request is within the rate limit.

        Records the current timestamp and prunes expired entries.
        """
        now = self.time_fn()
        bucket = self._buckets.setdefault(client_key, [])

        # Prune timestamps outside the window
        boundary = int(now - self.window_seconds)  # BUG_46: same truncation bug
        prune_idx = bisect.bisect_left(bucket, boundary)
        self._buckets[client_key] = bucket = bucket[prune_idx:]

        count = sliding_window_count(bucket, self.window_seconds, now)

        if count >= self.max_requests:
            return False

        bisect.insort(bucket, now)
        return True

    def current_count(self, client_key: str) -> int:
        """Return the current request count in the window for a client."""
        now = self.time_fn()
        bucket = self._buckets.get(client_key, [])
        return sliding_window_count(bucket, self.window_seconds, now)
