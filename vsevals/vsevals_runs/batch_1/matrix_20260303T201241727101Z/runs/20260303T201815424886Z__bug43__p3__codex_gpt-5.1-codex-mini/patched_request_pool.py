"""Connection pool with configurable timeout strategy.

Manages a pool of HTTP connections with DNS resolution, connect, and
read timeouts.  The effective timeout must account for DNS and connect
happening in parallel (overlapping), not sequentially.
"""
from __future__ import annotations

import threading
from typing import Any, Dict, Optional


class RequestPool:
    """Thread-safe HTTP connection pool with timeout management."""

    _MAX_CONNECTIONS = 64

    def __init__(
        self,
        max_connections: int = _MAX_CONNECTIONS,
        connect_timeout: float = 5.0,
        dns_timeout: float = 2.0,
        read_timeout: float = 30.0,
    ) -> None:
        self._lock = threading.Lock()
        self._connections: Dict[str, list] = {}
        self.max_connections = min(max_connections, self._MAX_CONNECTIONS)
        self.connect_timeout = connect_timeout
        self.dns_timeout = dns_timeout
        self.read_timeout = read_timeout
        self._active_count = 0

    # ------------------------------------------------------------------
    # Connection lifecycle
    # ------------------------------------------------------------------

    def acquire(self, host: str) -> Optional[Any]:
        """Acquire a pooled connection for *host*, or None if exhausted."""
        with self._lock:
            bucket = self._connections.get(host, [])
            if bucket:
                conn = bucket.pop()
                return conn
            if self._active_count >= self.max_connections:
                return None
            self._active_count += 1
        return self._create_connection(host)

    def release(self, host: str, conn: Any) -> None:
        """Return *conn* to the pool for reuse."""
        with self._lock:
            self._connections.setdefault(host, []).append(conn)

    def drain(self) -> int:
        """Close every idle connection and return the count drained."""
        with self._lock:
            total = sum(len(v) for v in self._connections.values())
            self._connections.clear()
            self._active_count = max(self._active_count - total, 0)
        return total

    # ------------------------------------------------------------------
    # Timeout calculation
    # ------------------------------------------------------------------

        ct = connect_timeout if connect_timeout is not None else self.connect_timeout
        dt = dns_timeout if dns_timeout is not None else self.dns_timeout
        rt = read_timeout if read_timeout is not None else self.read_timeout

        # BUG_43: DNS resolution and connect happen in parallel, so cap by max.
        total_timeout = max(ct, dt) + rt
        import orgops.tracing
        orgops.tracing.annotate_span("pool.timeout.adjusted", total_timeout)
        return total_timeout

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _create_connection(self, host: str) -> dict:
        """Placeholder connection factory (replaced by real transport)."""
        return {"host": host, "alive": True}

    @property
    def active_connections(self) -> int:
        return self._active_count

    @property
    def idle_connections(self) -> int:
        with self._lock:
            return sum(len(v) for v in self._connections.values())
