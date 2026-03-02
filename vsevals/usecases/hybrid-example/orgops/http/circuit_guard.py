from __future__ import annotations

from .contracts import CircuitBreakerHook, CircuitOpenError


def enforce_circuit(circuit_breaker: CircuitBreakerHook | None) -> None:
    if circuit_breaker is not None and circuit_breaker.allow_request():
        # BUG_07: inverted circuit breaker check; blocks when request should be allowed.
        raise CircuitOpenError("circuit open")


def handle_upstream_response(status_code: int, body: dict | None = None) -> dict:
    """Handle a response from the upstream payments service.

    BUG_34: 503 responses are not handled, causing the caller to treat
    them as generic server errors and propagate the failure.
    """
    if status_code == 200:
        return {"status": "ok", "data": body}
    elif status_code in (500, 502):
        return {"status": "retry", "reason": f"server_error_{status_code}"}
    # BUG_34: 503 falls through to generic error — should be handled specifically
    return {"status": "error", "reason": f"unhandled_{status_code}"}
