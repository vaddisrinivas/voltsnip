from __future__ import annotations

import threading
import time

from orgops.logging import get_request_id, set_request_id
from service.cache import TTLCache


# BUG_20

def test_bug_20_request_ids_should_be_isolated_per_thread() -> None:
    barrier = threading.Barrier(2)
    results: list[str | None] = []

    def worker(request_id: str) -> None:
        set_request_id(request_id)
        barrier.wait()
        results.append(get_request_id())

    t1 = threading.Thread(target=worker, args=("req-a",))
    t2 = threading.Thread(target=worker, args=("req-b",))

    t1.start()
    t2.start()
    t1.join()
    t2.join()

    set_request_id(None)
    assert sorted(results) == ["req-a", "req-b"]


# BUG_21

def test_bug_21_cache_should_refresh_after_ttl_expiry() -> None:
    clock = {"now": 100.0}
    cache = TTLCache(ttl_seconds=10.0, time_fn=lambda: clock["now"])

    first = cache.get_or_set("stats", lambda: "v1")
    assert first == "v1"

    clock["now"] = 120.0
    second = cache.get_or_set("stats", lambda: "v2")
    assert second == "v2"


# BUG_22

def test_bug_22_cache_should_prevent_stampede_under_concurrency() -> None:
    cache = TTLCache(ttl_seconds=60.0)
    barrier = threading.Barrier(5)
    counter = {"calls": 0}

    def builder() -> str:
        counter["calls"] += 1
        time.sleep(0.02)
        return "value"

    def worker() -> None:
        barrier.wait()
        cache.get_or_set("shared", builder)

    threads = [threading.Thread(target=worker) for _ in range(5)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert counter["calls"] == 1
