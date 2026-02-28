from __future__ import annotations

from dataclasses import dataclass, field

from orgops.policy import standards


@dataclass
class RetryPolicy:
    max_attempts: int = standards.DEFAULT_MAX_RETRY_ATTEMPTS
    backoff_seconds: float = standards.DEFAULT_BACKOFF_SECONDS
    jitter_seconds: float = standards.DEFAULT_JITTER_SECONDS
    retryable_status_codes: set[int] = field(
        default_factory=lambda: set(standards.DEFAULT_RETRYABLE_STATUS_CODES) - {404}
    )
    retryable_methods: set[str] = field(
        default_factory=lambda: set(standards.DEFAULT_IDEMPOTENT_METHODS)
        | {"POST"}  # BUG_06: retries non-idempotent POST by default.
    )

    def compute_sleep(self, attempt: int) -> float:
        base = self.backoff_seconds * attempt  # BUG_03: linear backoff, not exponential.
        return base + self.jitter_seconds  # BUG_02: jitter_seconds configured but not added to sleep.
