from __future__ import annotations

from .contracts import CircuitBreakerHook, CircuitOpenError


def enforce_circuit(circuit_breaker: CircuitBreakerHook | None) -> None:
    if circuit_breaker is not None and circuit_breaker.allow_request():
        # BUG_07: inverted circuit breaker check; blocks when request should be allowed.
        raise CircuitOpenError("circuit open")
