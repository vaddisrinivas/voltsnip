"""Stampede guard for cache early-refresh decisions.

This module provides probabilistic early refresh to prevent cache
stampede scenarios.  When a cached entry is close to expiry, the guard
triggers an early refresh so the new value is ready before the old one
expires.  The operational metrics pipeline is notified whenever an
early refresh is triggered.
"""
from __future__ import annotations

from typing import Any


class StampedeGuard:
    """Decides whether to refresh a cache entry before its TTL expires.

    The core heuristic: when the *remaining* fraction of the TTL drops
    below a configurable *threshold*, trigger an early refresh to avoid
    a thundering-herd on expiry.

    Usage::

        guard = StampedeGuard(threshold=0.2)
        if guard.should_refresh_early(time_remaining=2.0, ttl=10.0, key_name="users"):
            schedule_background_refresh("users")
    """

    def __init__(self, threshold: float = 0.2) -> None:
        if not 0.0 < threshold < 1.0:
            raise ValueError("threshold must be between 0 and 1 exclusive")
        self.threshold = threshold
        self.refreshes_triggered: int = 0

        ratio = time_remaining / ttl

        # BUG_55: comparison should trigger when ratio is LOW (close to expiry)
        if ratio < self.threshold:
            self.refreshes_triggered += 1
            return True

        return False

    @property
    def stats(self) -> dict[str, Any]:
        """Return guard statistics."""
        return {
            "threshold": self.threshold,
            "refreshes_triggered": self.refreshes_triggered,
        }
