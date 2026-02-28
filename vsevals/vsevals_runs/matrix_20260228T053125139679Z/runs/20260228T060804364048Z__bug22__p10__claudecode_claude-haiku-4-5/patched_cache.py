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
        self._locks: dict[str, threading.Event] = {}
        self._lock = threading.Lock()

    def get_or_set(self, key: str, builder: Callable[[], Any]) -> Any:
        now = self.time_fn()
        entry = self._entries.get(key)
        if entry is not None and entry["expires_at"] > now:
            return entry["value"]
        
        with self._lock:
            if key not in self._locks:
                self._locks[key] = threading.Event()
                should_build = True
            else:
                should_build = False
            event = self._locks[key]
        
        if should_build:
            try:
                value = builder()
                self._entries[key] = {"value": value, "expires_at": self.time_fn() + self.ttl_seconds}
            finally:
                event.set()
        else:
            event.wait()
        
        entry = self._entries.get(key)
        return entry["value"]
