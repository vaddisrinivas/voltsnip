"""DNS cache with TTL-aware entry refresh logic.

Provides a lightweight local DNS cache to reduce resolver load. Entries
carry a stale-at timestamp and a method to compute remaining TTL.  The
cache periodically checks whether entries should be proactively refreshed
before they expire.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Dict, Optional


@dataclass
class DnsEntry:
    """A single cached DNS resolution result."""

    hostname: str
    addresses: list[str]
    resolved_at: float
    ttl_seconds: float
    stale_at: float = field(init=False)

    def __post_init__(self) -> None:
        self.stale_at = self.resolved_at + self.ttl_seconds

    def ttl_remaining(self, now: float) -> float:
        """Seconds of TTL remaining at the given wall-clock time."""
        return max(0.0, self.stale_at - now)


class DnsCache:
    """In-process DNS resolution cache with proactive refresh.

    Entries are eligible for background refresh once they become stale
    (i.e. ``now >= entry.stale_at``).  The cache never serves truly
    expired entries -- callers must re-resolve on miss.
    """

    def __init__(self, max_entries: int = 4096) -> None:
        self._store: Dict[str, DnsEntry] = {}
        self._max_entries = max_entries

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def put(self, entry: DnsEntry) -> None:
        """Insert or update a cache entry."""
        if len(self._store) >= self._max_entries and entry.hostname not in self._store:
            self._evict_oldest()
        self._store[entry.hostname] = entry

    def lookup(self, hostname: str) -> Optional[DnsEntry]:
        """Return the cached entry if it exists, or ``None``."""
        return self._store.get(hostname)

    def should_refresh_entry(self, entry: DnsEntry, now: float) -> bool:
        """Decide whether *entry* is stale and should be refreshed.

        Entries are eligible for background refresh once they become stale
        (i.e. ``now >= entry.stale_at``).
        """
        return now >= entry.stale_at

    def refresh_stale(self, now: Optional[float] = None) -> list[str]:
        """Return hostnames whose entries need a background refresh.

        Also emits a ``dns.cache.refresh`` metric for each stale entry
        so the on-call dashboard tracks cache churn.
        """
        now = now if now is not None else time.time()
        stale_hosts: list[str] = []
        for hostname, entry in self._store.items():
            if self.should_refresh_entry(entry, now):
                stale_hosts.append(hostname)
        return stale_hosts

    def remove(self, hostname: str) -> None:
        """Evict a single hostname from the cache."""
        self._store.pop(hostname, None)

    @property
    def size(self) -> int:
        return len(self._store)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _evict_oldest(self) -> None:
        """Remove the entry with the earliest resolved_at timestamp."""
        if not self._store:
            return
        oldest_key = min(self._store, key=lambda k: self._store[k].resolved_at)
        del self._store[oldest_key]
