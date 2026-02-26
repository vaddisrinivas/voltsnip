from __future__ import annotations

from typing import Any

import httpx

from .circuit_guard import enforce_circuit
from .contracts import CircuitBreakerHook
from .request_config import resolve_request_config
from .retry_policy import RetryPolicy


class OrgHTTPClient:
    def __init__(
        self,
        client: httpx.Client | None = None,
        retry_policy: RetryPolicy | None = None,
        circuit_breaker: CircuitBreakerHook | None = None,
        sleep_fn: callable | None = None,
    ) -> None:
        self.client = client or httpx.Client()
        self.retry_policy = retry_policy or RetryPolicy()
        self.circuit_breaker = circuit_breaker
        self.sleep_fn = sleep_fn or (lambda seconds: None)

    def request(
        self,
        method: str,
        url: str,
        *,
        timeout: float | None = None,
        max_attempts: int | None = None,
        **kwargs: Any,
    ) -> httpx.Response:
        method, attempts, request_timeout = resolve_request_config(
            retry_policy=self.retry_policy,
            method=method,
            timeout=timeout,
            max_attempts=max_attempts,
        )

        for attempt in range(1, attempts + 1):
            enforce_circuit(self.circuit_breaker)

            try:
                response = self.client.request(method, url, timeout=request_timeout, **kwargs)
            except httpx.HTTPError:
                if self.circuit_breaker is not None:
                    self.circuit_breaker.record_failure()
                if attempt >= attempts:
                    raise
                self.sleep_fn(self.retry_policy.compute_sleep(attempt))
                continue

            if (
                response.status_code in self.retry_policy.retryable_status_codes
                and method in self.retry_policy.retryable_methods
                and attempt < attempts
            ):
                if self.circuit_breaker is not None:
                    self.circuit_breaker.record_failure()
                self.sleep_fn(self.retry_policy.compute_sleep(attempt))
                continue

            if self.circuit_breaker is not None:
                self.circuit_breaker.record_success()
            return response

        raise RuntimeError("request exhausted without response")

    def get(self, url: str, **kwargs: Any) -> httpx.Response:
        return self.request("GET", url, **kwargs)

    def post(self, url: str, **kwargs: Any) -> httpx.Response:
        return self.request("POST", url, **kwargs)
