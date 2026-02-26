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
        self._lock = threading.Lock()

    def get_or_set(self, key: str, builder: Callable[[], Any]) -> Any:
        while True:
            now = self.time_fn()
            with self._lock:
                entry = self._entries.get(key)
                if entry is not None:
                    expires = entry.get("expires_at")
                    if expires is not None and expires > now:
                        return entry["value"]
                    wait_event = entry.get("ready")
                    if isinstance(wait_event, threading.Event):
                        creator = False
                    else:
                        wait_event = threading.Event()
                        self._entries[key] = {"ready": wait_event}
                        creator = True
                else:
                    wait_event = threading.Event()
                    self._entries[key] = {"ready": wait_event}
                    creator = True

            if not creator:
                wait_event.wait()
                continue

            try:
                value = builder()
            except Exception:
                with self._lock:
                    current = self._entries.get(key)
                    if current is not None and current.get("ready") is wait_event:
                        self._entries.pop(key, None)
                wait_event.set()
                raise

            with self._lock:
                self._entries[key] = {"value": value, "expires_at": self.time_fn() + self.ttl_seconds}
            wait_event.set()
            return value
