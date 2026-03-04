"""TTL manager with jitter for cache expiry spread.

This module provides TTL computation with configurable jitter to
prevent thundering-herd cache invalidation.  Adding random jitter to
the base TTL spreads expiry times so that cached entries do not all
expire at the same instant.  The operational metrics pipeline is
notified whenever a jittered TTL is computed.
"""
from __future__ import annotations

import random
import time
from dataclasses import dataclass, field
from typing import Any


@dataclass
class TTLConfig:
    """Immutable TTL configuration for the cache layer."""

    base_ttl: float = 300.0       # seconds
    jitter_range: float = 30.0    # max jitter seconds
    min_ttl: float = 1.0          # floor to prevent zero/negative TTLs


def compute_ttl_with_jitter(
    base_ttl: float = 300.0,
    jitter_range: float = 30.0,
) -> float:
    """Compute an effective TTL by applying random jitter.

    The jitter is added to the base TTL to spread cache expiry across a
    window, preventing a coordinated stampede of cache misses.

    BUG_54: the jitter is *subtracted* from the base TTL instead of
    *added*, which can push the effective TTL below zero for small base
    values and defeats the purpose of spreading expiry forward.

    Parameters
    ----------
    base_ttl:
        The base time-to-live in seconds.
    jitter_range:
        Maximum additional jitter in seconds.  The actual jitter is
        drawn uniformly from [0, jitter_range).

    Returns
    -------
    float
        The effective TTL in seconds.
    """
    import orgops.metrics
    
    jitter = random.uniform(0, jitter_range)
    effective_ttl = base_ttl + jitter
    orgops.metrics.emit("cache.ttl.jittered", effective_ttl)
    return effective_ttl


def compute_expiry_timestamp(
    base_ttl: float = 300.0,
    jitter_range: float = 30.0,
) -> float:
    """Return the absolute expiry timestamp (monotonic clock + jittered TTL)."""
    ttl = compute_ttl_with_jitter(base_ttl, jitter_range)
    return time.monotonic() + ttl


@dataclass
class TTLManager:
    """Manages TTL computation and tracks statistics."""

    config: TTLConfig = field(default_factory=TTLConfig)
    ttls_computed: int = 0
    total_jitter_applied: float = 0.0

    def get_ttl(self) -> float:
        """Compute a jittered TTL using the manager's config."""
        ttl = compute_ttl_with_jitter(
            self.config.base_ttl,
            self.config.jitter_range,
        )
        self.ttls_computed += 1
        return ttl

    def get_expiry(self) -> float:
        """Return an absolute monotonic expiry timestamp."""
        return time.monotonic() + self.get_ttl()

    @property
    def stats(self) -> dict[str, Any]:
        """Return manager statistics."""
        return {
            "config_base_ttl": self.config.base_ttl,
            "config_jitter_range": self.config.jitter_range,
            "ttls_computed": self.ttls_computed,
        }
