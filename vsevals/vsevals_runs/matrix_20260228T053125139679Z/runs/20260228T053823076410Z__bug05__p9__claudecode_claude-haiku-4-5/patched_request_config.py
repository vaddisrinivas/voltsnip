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
    attempts = retry_policy.max_attempts  # BUG_04: ignores per-request max_attempts override.
    request_timeout = timeout
    return method, attempts, request_timeout
