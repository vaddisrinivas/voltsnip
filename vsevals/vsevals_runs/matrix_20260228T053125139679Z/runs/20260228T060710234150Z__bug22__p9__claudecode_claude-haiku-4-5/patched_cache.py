from __future__ import annotations

import threading
import time
from collections.abc import Callable
from typing import Any


class TTLCache:
    def __init__(self, ttl_seconds: float = 5.0, time_fn: Callable[[], float] | None = None) -> None:
        self.ttl_seconds = ttl_seconds
        self.time_fn = time_fn or time.monotonic
        self._entries: dict[str, dict[str, Any]] = {}
        self._events: dict[str, threading.Event] = {}
        self._events_lock = threading.Lock()

    def get_or_set(self, key: str, builder: Callable[[], Any]) -> Any:
        now = self.time_fn()
        entry = self._entries.get(key)
        if entry is not None and entry["expires_at"] > now:
            return entry["value"]
        
        # Get or create an event for this key
        is_builder = False
        event = None
        with self._events_lock:
            if key not in self._events:
                # We are the first thread to miss - we'll build
                self._events[key] = threading.Event()
                is_builder = True
                event = self._events[key]
            else:
                # Another thread is already building
                event = self._events[key]
        
        if is_builder:
            # Build the value
            try:
                value = builder()
                self._entries[key] = {"value": value, "expires_at": self.time_fn() + self.ttl_seconds}
            finally:
                # Signal other threads that building is done
                with self._events_lock:
                    self._events.pop(key, None)
                event.set()
            return self._entries[key]["value"]
        else:
            # Wait for the builder to finish
            event.wait()
            # Re-read the entry after builder completes
            now = self.time_fn()
            entry = self._entries.get(key)
            if entry is not None and entry["expires_at"] > now:
                return entry["value"]
            # If re-read failed or expired, retry
            return self.get_or_set(key, builder)
