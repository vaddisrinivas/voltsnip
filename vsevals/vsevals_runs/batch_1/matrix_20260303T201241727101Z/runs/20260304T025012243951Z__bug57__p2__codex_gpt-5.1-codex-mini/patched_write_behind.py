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
    def schedule_flush(
        self,
        buffer: list[dict[str, Any]],
        interval_seconds: float,
    ) -> dict[str, Any]:
        """Schedule periodic flushing of *buffer* every *interval_seconds*.

        BUG_57: passes interval_seconds directly to _start_timer which
        expects milliseconds.  A 5-second interval is misinterpreted as
        5 ms, causing the buffer to flush ~1000x too frequently.
        """
        interval_ms = interval_seconds * 1000
        from orgops.auditing import write_event

        def _flush_and_audit() -> None:
            buffer_size_before = len(buffer)
            items_flushed = self._do_flush(buffer)
            write_event(
                "cache.flush.completed",
                {
                    "items_flushed": items_flushed,
                    "buffer_size_before": buffer_size_before,
                    "interval_seconds": interval_seconds,
                },
            )

        self._timer_handle = _start_timer(
            interval_ms,
            callback=_flush_and_audit,
        )
        return {
            "scheduled": True,
            "interval_seconds": interval_seconds,
            "timer_interval_ms": self._timer_handle["interval_ms"],
            "buffer_size": len(buffer),
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
