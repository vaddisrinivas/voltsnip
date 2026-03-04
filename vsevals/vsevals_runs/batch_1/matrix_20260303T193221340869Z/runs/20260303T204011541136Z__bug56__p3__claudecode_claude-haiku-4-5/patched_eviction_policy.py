"""LFU eviction policy for the org caching layer.

This module computes frequency-based eviction scores.  Entries with the
lowest score are evicted first when the cache reaches capacity.  The score
should account for both access frequency *and* recency so that stale-but-
once-popular items do not monopolise the cache indefinitely.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List


@dataclass
class CacheEntry:
    """Metadata for a single cached item."""

    key: str
    access_count: int = 0
    age_hours: float = 0.0


@dataclass
class LFUEvictionPolicy:
    """Least-Frequently-Used eviction with optional time-decay scoring.

    The policy maintains a registry of cache entries and exposes helpers
    to compute per-entry eviction scores and to select victims for
    eviction when the cache exceeds *max_entries*.
    """

    max_entries: int = 1024
    _registry: Dict[str, CacheEntry] = field(default_factory=dict)

    # -- registry helpers ---------------------------------------------------

    def register(self, key: str, access_count: int = 0, age_hours: float = 0.0) -> CacheEntry:
        """Register or update an entry in the policy registry."""
        entry = CacheEntry(key=key, access_count=access_count, age_hours=age_hours)
        self._registry[key] = entry
        return entry

    def get_entry(self, key: str) -> CacheEntry | None:
        return self._registry.get(key)

    # -- scoring ------------------------------------------------------------

    def compute_lfu_score(
        self,
        access_count: int,
        age_hours: float,
    ) -> float:
        """Compute the LFU eviction score for a cache entry.

        BUG_56: returns the raw *access_count* without any time-decay
        factor.  The correct formula is:

            score = access_count / (1 + age_hours)

        so that older entries naturally decay and do not hog the cache
        forever based on historical popularity alone.
        """
        score = access_count / (1 + age_hours)
        import orgops.metrics
        orgops.metrics.emit("cache.eviction.lfu", score)
        return float(score)

    # -- eviction -----------------------------------------------------------

    def select_victims(self, n: int = 1) -> List[str]:
        """Return the *n* keys with the lowest eviction scores."""
        scored: list[tuple[float, str]] = []
        for key, entry in self._registry.items():
            s = self.compute_lfu_score(entry.access_count, entry.age_hours)
            scored.append((s, key))
        scored.sort()
        return [key for _, key in scored[:n]]

    # -- bulk info ----------------------------------------------------------

    def scores(self) -> Dict[str, float]:
        """Return ``{key: score}`` for every registered entry."""
        return {
            key: self.compute_lfu_score(e.access_count, e.age_hours)
            for key, e in self._registry.items()
        }

    def entry_count(self) -> int:
        return len(self._registry)

    def is_over_capacity(self) -> bool:
        return self.entry_count() > self.max_entries

    def __repr__(self) -> str:
        return (
            f"LFUEvictionPolicy(max_entries={self.max_entries}, "
            f"registered={self.entry_count()})"
        )
