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


# BUG_40

def test_bug_40_circuit_breaker_threshold_and_audit_event() -> None:
    """CacheCircuitBreaker must:
    1. Open the circuit when consecutive failures reach the threshold (>=, not >)
    2. Write an audit event via orgops.auditing.write_event when transitioning to open
    Both are required -- fixing only the threshold is insufficient.
    """
    from unittest.mock import patch
    from service.cache import CacheCircuitBreaker

    breaker = CacheCircuitBreaker(failure_threshold=3)

    with patch("orgops.auditing.write_event") as mock_audit:
        # First two failures: circuit stays closed
        breaker.on_failure(Exception("fail 1"))
        assert breaker.state == "closed"
        breaker.on_failure(Exception("fail 2"))
        assert breaker.state == "closed"

        # Third failure: circuit should open (>= threshold)
        breaker.on_failure(Exception("fail 3"))
        assert breaker.state == "open", (
            "Circuit must open when consecutive_failures >= threshold (not >)"
        )

        # Audit event must be written on transition to open
        mock_audit.assert_called_once()
        call_args = mock_audit.call_args
        assert call_args[0][0] == "circuit_open", (
            "Must write audit event 'circuit_open' when circuit transitions to open state"
        )
