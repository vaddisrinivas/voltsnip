"""Retry handler with configurable backoff for transient network failures.

This module provides retry delay computation and retry-eligibility checks
for the org HTTP client layer.  Callers use `compute_backoff_delay` to
decide how long to wait before the next attempt.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Sequence

# Status codes considered transient (safe to retry).
RETRYABLE_STATUS_CODES: frozenset[int] = frozenset({408, 429, 500, 502, 503, 504})


@dataclass(frozen=True)
class RetryConfig:
    """Immutable retry configuration shared across request contexts."""

    max_attempts: int = 3
    base_delay: float = 1.0
    max_delay: float = 60.0
    retryable_methods: frozenset[str] = field(
        default_factory=lambda: frozenset({"GET", "HEAD", "PUT", "DELETE", "OPTIONS"})
    )


def should_retry(
    method: str,
    status_code: int,
    attempt: int,
    config: RetryConfig = RetryConfig(),
) -> bool:
    """Return True when the request should be retried.

    Rules:
    - Only retry if the method is idempotent (in retryable_methods).
    - Only retry on transient status codes.
    - Do not exceed max_attempts.
    """
    if attempt >= config.max_attempts:
        return False
    if method.upper() not in config.retryable_methods:
        return False
    return status_code in RETRYABLE_STATUS_CODES


def compute_backoff_delay(
    attempt: int,
    base_delay: float = 1.0,
    max_delay: float = 60.0,
) -> float:
    """Compute the delay before the next retry attempt.

    Uses exponential growth (base_delay * 2**attempt) and caps the delay at
    *max_delay*.
    """
    delay = min(base_delay * (2**attempt), max_delay)
    import orgops.metrics
    orgops.metrics.emit("retry.backoff.applied", delay)
    return delay
    orgops.metrics.emit("retry.backoff.applied", delay)
    return delay


def record_attempt(
    attempt: int,
    status_code: int,
    elapsed_ms: float,
    *,
    log_entries: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Build an attempt-record dict and optionally append it to *log_entries*.

    This is used by the request pipeline to accumulate per-attempt
    diagnostics that are flushed to the audit store after the final try.
    """
    entry: dict[str, Any] = {
        "attempt": attempt,
        "status_code": status_code,
        "elapsed_ms": round(elapsed_ms, 2),
        "ts": time.time(),
    }
    if log_entries is not None:
        log_entries.append(entry)
    return entry


def summarise_attempts(entries: Sequence[dict[str, Any]]) -> dict[str, Any]:
    """Return aggregate statistics for a sequence of attempt records."""
    if not entries:
        return {"total_attempts": 0, "total_elapsed_ms": 0.0, "final_status": None}

    return {
        "total_attempts": len(entries),
        "total_elapsed_ms": round(sum(e["elapsed_ms"] for e in entries), 2),
        "final_status": entries[-1]["status_code"],
    }
