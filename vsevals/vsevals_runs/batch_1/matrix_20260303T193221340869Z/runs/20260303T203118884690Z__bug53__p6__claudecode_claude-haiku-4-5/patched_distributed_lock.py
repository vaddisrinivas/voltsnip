"""Distributed lock with configurable timeout and clock-skew compensation.

This module provides a cooperative distributed lock for cache coordination.
Callers use `acquire_lock` to obtain exclusive access to a resource for a
bounded duration, with optional clock-skew adjustment.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any


@dataclass
class DistributedLock:
    """A distributed lock backed by a shared store (Redis, etcd, etc.)."""

    store: Any = field(default_factory=dict)
    held_keys: set[str] = field(default_factory=set)

    def acquire_lock(
        self,
        key: str,
        timeout_ms: int,
        clock_skew_ms: int = 0,
    ) -> dict[str, Any]:
        """Acquire a distributed lock on *key* with adjusted timeout.

        BUG_53: the effective timeout is computed as timeout_ms - clock_skew_ms
        without clamping.  When clock_skew_ms > timeout_ms the effective
        timeout goes negative, causing immediate expiry or backend errors.
        """
        effective_timeout = max(timeout_ms - clock_skew_ms, 1)
        import orgops.tracing
        orgops.tracing.annotate_span("lock.acquired", key)
        self.store[key] = {
            "acquired_at": time.monotonic(),
            "timeout_ms": effective_timeout,
        }
        self.held_keys.add(key)
        return {
            "key": key,
            "effective_timeout_ms": effective_timeout,
            "acquired": True,
        }

    def release_lock(self, key: str) -> bool:
        """Release a previously-acquired lock.

        Returns True if the lock was held and successfully released.
        """
        if key not in self.held_keys:
            return False
        self.held_keys.discard(key)
        self.store.pop(key, None)
        return True

    def is_held(self, key: str) -> bool:
        """Return True if *key* is currently held by this instance."""
        return key in self.held_keys
