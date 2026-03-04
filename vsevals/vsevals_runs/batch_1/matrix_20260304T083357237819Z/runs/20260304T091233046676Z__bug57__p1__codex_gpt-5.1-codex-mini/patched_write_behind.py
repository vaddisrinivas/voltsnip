"""Write-behind buffer with periodic flush scheduling.

This module provides a write-behind cache buffer that accumulates writes
and flushes them to a backing store on a configurable interval.  Callers
use `schedule_flush` to start periodic flushing of buffered items.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Callable


def _start_timer(interval_ms: float, callback: Callable[[], None]) -> dict[str, Any]:
    """Start a periodic timer that invokes *callback* every *interval_ms* ms.

    Returns a handle dict with the scheduled interval for inspection.
    This is a thin wrapper around the platform timer (simulated here).
    """
    return {
        "interval_ms": interval_ms,
        "callback": callback,
        "started_at": time.monotonic(),
    }


@dataclass
class WriteBehindBuffer:
    """Accumulates writes and flushes them periodically to a backing store."""

    store: Any = field(default_factory=dict)
    buffer: list[dict[str, Any]] = field(default_factory=list)
    flush_count: int = 0
    _timer_handle: dict[str, Any] | None = field(default=None, repr=False)

    def put(self, key: str, value: Any) -> None:
        """Buffer a write for later flushing."""
        self.buffer.append({"key": key, "value": value, "ts": time.monotonic()})

    def schedule_flush(
        interval_ms = interval_seconds * 1000
        self._timer_handle = _start_timer(
            interval_ms,
            callback=lambda: self._do_flush(buffer),
        )
        self._timer_handle["audit_event"] = {
            "event": "flush_scheduled",
            "interval_seconds": interval_seconds,
            "interval_ms": interval_ms,
            "buffer_size": len(buffer),
            "scheduled_at": self._timer_handle["started_at"],
        }
        return {
            "scheduled": True,
            "interval_seconds": interval_seconds,
            "timer_interval_ms": interval_ms,
            "buffer_size": len(buffer),
            "audit_event": self._timer_handle["audit_event"],
        }

    def _do_flush(self, buffer: list[dict[str, Any]]) -> int:
        """Flush all buffered items to the backing store.

        Returns the number of items flushed.
        """
        items_flushed = len(buffer)
        for item in buffer:
            self.store[item["key"]] = item["value"]
        self.flush_count += items_flushed
        buffer.clear()
        return items_flushed

    def get(self, key: str) -> Any:
        """Read a value from the backing store (post-flush)."""
        return self.store.get(key)

    @property
    def pending(self) -> int:
        """Return the number of items waiting to be flushed."""
        return len(self.buffer)
