from __future__ import annotations

from .retry_policy import RetryPolicy


def resolve_request_config(
    *,
    retry_policy: RetryPolicy,
    method: str,
    timeout: float | None,
    max_attempts: int | None,
) -> tuple[str, int, float | None]:
    method = method.upper()
    attempts = max_attempts if max_attempts is not None else retry_policy.max_attempts
    request_timeout = (
        timeout if timeout is not None and method == "GET" else None
    )  # BUG_05: timeout only applied to GET and omitted otherwise.
    return method, attempts, request_timeout
