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
        self._pending: dict[str, threading.Event] = {}
        self._lock = threading.Lock()

    def get_or_set(self, key: str, builder: Callable[[], Any]) -> Any:
        now = self.time_fn()
        entry = self._entries.get(key)
        if entry is not None and entry["expires_at"] > now:
            return entry["value"]
        
        with self._lock:
            if key in self._pending:
                event = self._pending[key]
                is_builder = False
            else:
                event = threading.Event()
                self._pending[key] = event
                is_builder = True
        
        if is_builder:
            try:
                value = builder()
                self._entries[key] = {"value": value, "expires_at": self.time_fn() + self.ttl_seconds}
                return value
            finally:
                with self._lock:
                    event.set()
                    del self._pending[key]
        else:
            event.wait()
            entry = self._entries.get(key)
            if entry is not None:
                return entry["value"]
