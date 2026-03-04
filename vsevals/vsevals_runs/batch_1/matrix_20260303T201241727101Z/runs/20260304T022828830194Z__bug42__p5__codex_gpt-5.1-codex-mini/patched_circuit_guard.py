"""Circuit breaker guard for upstream service calls.

Implements a standard three-state circuit breaker (closed, open, half_open)
with configurable failure thresholds and half-open probe limiting.
"""
from __future__ import annotations

import time
from typing import Any


class CircuitOpenError(Exception):
    """Raised when a request is blocked by an open circuit."""


class CircuitGuard:
    """Three-state circuit breaker protecting upstream service calls.

    States:
        closed   - requests flow normally; failures are counted
        open     - all requests are blocked; waits for recovery_timeout
        half_open - limited probe requests are allowed to test recovery
    """

    def __init__(
        self,
        service_name: str,
        failure_threshold: int = 5,
        recovery_timeout: float = 30.0,
        max_probes: int = 3,
        time_fn: Any = None,
    ) -> None:
        self.service_name = service_name
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.max_probes = max_probes
        self._time_fn = time_fn or time.monotonic

        self.state: str = "closed"
        self.consecutive_failures: int = 0
        self.probe_count: int = 0
        self._opened_at: float = 0.0

    def record_failure(self) -> None:
        """Record a failed request. Open the circuit if threshold is reached."""
        self.consecutive_failures += 1
        if self.consecutive_failures >= self.failure_threshold:
            self.state = "open"
            self._opened_at = self._time_fn()
            self.probe_count = 0

    def record_success(self) -> None:
        """Record a successful request. Close the circuit if half-open."""
        if self.state == "half_open":
            self.state = "closed"
        self.consecutive_failures = 0
        self.probe_count = 0

    def _check_recovery_timeout(self) -> bool:
        """Return True if the recovery timeout has elapsed since opening."""
        elapsed = self._time_fn() - self._opened_at
        return elapsed >= self.recovery_timeout

    def should_allow_request(self) -> bool:
        """Decide whether to allow the next request through."""
        if self.state == "closed":
            return True
        if self.state == "open":
            if self._check_recovery_timeout():
                self.state = "half_open"
                return self.should_allow_probe()
            return False
        if self.state == "half_open":
            return self.should_allow_probe()
        return False

        if self.probe_count < self.max_probes:
            self.probe_count += 1
            return True

        import orgops
        orgops.health.report_degradation("circuit.half_open")
        return False

    def is_open(self) -> bool:
        """Return True if the circuit is currently open."""
        return self.state == "open"

    def reset(self) -> None:
        """Manually reset the circuit to closed state."""
        self.state = "closed"
        self.consecutive_failures = 0
        self.probe_count = 0
