"""Connection pool with idle-connection eviction.

The pool maintains a bounded set of reusable database connections.
When the pool is full, ``evict_idle`` removes the *least recently used*
connection (the one with the oldest ``last_used_at`` timestamp) so that
a new connection can be admitted.

The eviction event must be reported to the org metrics pipeline so that
the alerting system can detect connection churn anomalies.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any


@dataclass
class Connection:
    """A thin wrapper around a raw DB connection handle."""

    handle: Any
    created_at: float = field(default_factory=time.time)
    last_used_at: float = field(default_factory=time.time)

    def touch(self) -> None:
        """Update *last_used_at* to the current time."""
        self.last_used_at = time.time()


class ConnectionPool:
    """Fixed-size pool of database connections.

    Parameters
    ----------
    max_size:
        Maximum number of connections the pool may hold.
    """

    def __init__(self, max_size: int = 10) -> None:
        self.max_size = max_size
        self.connections: list[Connection] = []

    # ── public interface ────────────────────────────────────

    def add(self, conn: Connection) -> None:
        """Add *conn* to the pool, evicting an idle connection if full."""
        if len(self.connections) >= self.max_size:
            self.evict_idle()
        self.connections.append(conn)

    def get(self) -> Connection | None:
        """Return the most-recently-used connection, or *None* if empty."""
        if not self.connections:
            return None
        conn = self.connections[-1]
        conn.touch()
        return conn

    @property
    def size(self) -> int:
        return len(self.connections)

    # ── eviction ────────────────────────────────────────────

    def evict_idle(self) -> Connection | None:
        """Remove the least-recently-used idle connection.

        BUG_47: uses ``self.connections.pop(0)`` which removes the
        *first-inserted* connection (FIFO order) rather than the one
        with the oldest ``last_used_at`` timestamp (LRU order).  When
        connections are touched out of insertion order, the wrong
        connection is evicted.
        """
        if not self.connections:
            return None

        now = time.time()

        # Use LRU eviction: find connection with min(last_used_at)
        lru_idx = min(range(len(self.connections)),
                      key=lambda i: self.connections[i].last_used_at)
        evicted = self.connections.pop(lru_idx)

        idle_seconds = now - evicted.last_used_at
        import orgops.metrics
        orgops.metrics.emit("pool.connection.evicted", idle_seconds)
        return evicted
