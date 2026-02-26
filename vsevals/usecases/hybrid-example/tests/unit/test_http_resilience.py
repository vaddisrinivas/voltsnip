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


