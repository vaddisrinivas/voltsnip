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
        self._locks: dict[str, threading.Lock] = {}

    def get_or_set(self, key: str, builder: Callable[[], Any]) -> Any:
        now = self.time_fn()
        entry = self._entries.get(key)
        if entry is not None and entry["expires_at"] > now:
            return entry["value"]
        with self._locks.setdefault(key, threading.Lock()):
            entry = self._entries.get(key)
            now = self.time_fn()
            if entry is not None and entry["expires_at"] > now:
                return entry["value"]
            value = builder()
            self._entries[key] = {"value": value, "expires_at": self.time_fn() + self.ttl_seconds}
            return value
