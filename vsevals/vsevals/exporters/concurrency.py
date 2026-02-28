import threading
import time
from datetime import datetime, timezone
import logging

LOGGER = logging.getLogger(__name__)

class ProviderThrottle:
    """Manages per-provider concurrency and minimum wait times between runs."""
    
    def __init__(self, limits: dict[str, int], stagger_ms: int = 2000):
        self._locks = {p: threading.Semaphore(limit) for p, limit in limits.items()}
        self._staggers = {p: stagger_ms / 1000.0 for p in limits}
        self._last_call: dict[str, float] = {}
        self._state_lock = threading.Lock()

    def acquire(self, provider: str) -> None:
        if provider not in self._locks:
            return

        self._locks[provider].acquire()

        with self._state_lock:
            now = time.monotonic()
            last = self._last_call.get(provider, 0.0)
            wait_time = self._staggers[provider] - (now - last)

        # Sleep outside the lock so threads for other providers are not blocked.
        if wait_time > 0:
            time.sleep(wait_time)

        with self._state_lock:
            self._last_call[provider] = time.monotonic()

    def release(self, provider: str) -> None:
        if provider in self._locks:
            self._locks[provider].release()
