from __future__ import annotations

import httpx
import pytest

from orgops.http import CircuitBreakerHook, CircuitOpenError, OrgHTTPClient, RetryPolicy


class _RecordingBreaker(CircuitBreakerHook):
    def __init__(self, allow: bool) -> None:
        self.allow = allow
        self.successes = 0
        self.failures = 0

    def allow_request(self) -> bool:
        return self.allow

    def record_success(self) -> None:
        self.successes += 1

    def record_failure(self) -> None:
        self.failures += 1


class _CaptureClient:
    def __init__(self) -> None:
        self.timeouts: list[float | None] = []

    def request(self, method: str, url: str, timeout=None, **kwargs):
        self.timeouts.append(timeout)
        return httpx.Response(200, json={"ok": True})


# BUG_01

def test_bug_01_should_not_retry_on_404() -> None:
    calls = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["count"] += 1
        if calls["count"] == 1:
            return httpx.Response(404, json={"detail": "missing"})
        return httpx.Response(200, json={"ok": True})

    client = OrgHTTPClient(
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        retry_policy=RetryPolicy(max_attempts=2),
    )

    response = client.get("https://example.test/users/1")
    assert calls["count"] == 1
    assert response.status_code == 404


# BUG_02

def test_bug_02_backoff_should_include_jitter() -> None:
    policy = RetryPolicy(backoff_seconds=1.0, jitter_seconds=0.3)
    delay = policy.compute_sleep(2)
    assert delay > 2.0


# BUG_03

def test_bug_03_backoff_should_be_exponential() -> None:
    policy = RetryPolicy(backoff_seconds=0.5, jitter_seconds=0.0)
    delay = policy.compute_sleep(3)
    assert delay == pytest.approx(2.0)


# BUG_04

def test_bug_04_request_override_max_attempts_should_apply() -> None:
    calls = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["count"] += 1
        return httpx.Response(500, json={"detail": "boom"})

    client = OrgHTTPClient(
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        retry_policy=RetryPolicy(max_attempts=4),
    )

    response = client.get("https://example.test/unstable", max_attempts=1)
    assert calls["count"] == 1
    assert response.status_code == 500


# BUG_05

def test_bug_05_timeout_should_apply_to_all_methods() -> None:
    capture_client = _CaptureClient()
    client = OrgHTTPClient(client=capture_client, retry_policy=RetryPolicy(max_attempts=1))

    client.post("https://example.test/users", timeout=0.25, json={"x": 1})
    assert capture_client.timeouts == [0.25]


# BUG_06

def test_bug_06_post_should_not_retry_by_default() -> None:
    calls = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["count"] += 1
        if calls["count"] == 1:
            return httpx.Response(500, json={"detail": "first failure"})
        return httpx.Response(200, json={"ok": True})

    client = OrgHTTPClient(
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        retry_policy=RetryPolicy(max_attempts=2),
    )

    response = client.post("https://example.test/create", json={"name": "alice"})
    assert calls["count"] == 1
    assert response.status_code == 500


# BUG_07

def test_bug_07_circuit_breaker_should_allow_when_closed() -> None:
    breaker = _RecordingBreaker(allow=True)

    client = OrgHTTPClient(
        client=httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(200, json={"ok": True}))),
        retry_policy=RetryPolicy(max_attempts=1),
        circuit_breaker=breaker,
    )

    response = client.get("https://example.test/ping")
    assert response.status_code == 200


# BUG_33

def test_bug_33_persist_retry_outcome_should_flush_not_commit() -> None:
    """The org audit system uses post-flush hooks to read uncommitted rows.
    Calling commit() instead of flush() bypasses the audit trigger.
    """
    from unittest.mock import MagicMock
    from orgops.http.retry_policy import persist_retry_outcome

    session = MagicMock()
    session._audit_triggered = False
    outcome = {"attempt": 3, "status": "success", "latency_ms": 120}

    persist_retry_outcome(session, outcome)

    # The correct fix uses flush(), not commit()
    session.flush.assert_called_once()
    assert session.commit.call_count == 0, "Must use flush() instead of commit() to trigger audit hooks"


# BUG_34

def test_bug_34_handle_upstream_503_means_async_accepted() -> None:
    """The payments upstream uses 503 to mean 'accepted, processing async'.
    Standard retry logic for 503 is WRONG here -- must return accepted_async.
    """
    from orgops.http.circuit_guard import handle_upstream_response

    # 503 should return accepted_async status, NOT trigger retry
    result_503 = handle_upstream_response(503, {"job_id": "abc-123"})
    assert result_503["status"] == "accepted_async", "503 means async processing, not a server error"
    assert "retry" not in result_503["status"], "503 must NOT trigger retry for this upstream"

    # 500 and 502 SHOULD still trigger retry (normal behavior)
    result_500 = handle_upstream_response(500)
    assert result_500["status"] == "retry"

    result_502 = handle_upstream_response(502)
    assert result_502["status"] == "retry"

    # 200 should still work normally
    result_200 = handle_upstream_response(200, {"ok": True})
    assert result_200["status"] == "ok"


