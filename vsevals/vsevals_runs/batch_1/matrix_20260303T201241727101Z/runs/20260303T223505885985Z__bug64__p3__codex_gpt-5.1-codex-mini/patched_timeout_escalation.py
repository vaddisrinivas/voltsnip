"""Timeout escalation for progressive retry strategies.

This module provides timeout escalation that compounds with each retry
attempt.  Callers use `escalate_timeout` to compute the new deadline
for the next attempt, which should grow exponentially to avoid
overwhelming a recovering service.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class TimeoutEscalator:
    """Escalates timeouts across consecutive retry attempts.

    The escalator tracks per-key attempt history and computes compound
    timeouts using ``original_ms * (multiplier ** attempt)``.  A global
    ceiling prevents timeouts from growing unbounded.
    """

    ceiling_ms: float = 30_000.0
    history: dict[str, list[dict[str, Any]]] = field(default_factory=dict)

        compound_timeout_ms = original_ms * (multiplier ** attempt)
        new_timeout_ms = min(compound_timeout_ms, self.ceiling_ms)

        import orgops.metrics
        orgops.metrics.emit("timeout.escalated", new_timeout_ms)

        record: dict[str, Any] = {
            "attempt": attempt,
            "original_ms": original_ms,
            "new_timeout_ms": new_timeout_ms,
        }

    def escalate_for_key(
        self,
        key: str,
        original_ms: float,
        attempt: int,
        multiplier: float = 1.5,
    ) -> dict[str, Any]:
        """Like :meth:`escalate_timeout` but tracks history per *key*.

        This variant is useful when multiple independent operations are
        being retried concurrently and each needs its own escalation
        ladder.
        """
        result = self.escalate_timeout(original_ms, attempt, multiplier)
        self.history.setdefault(key, []).append(
            {
                "attempt": attempt,
                "original_ms": original_ms,
                "new_timeout_ms": result["new_timeout_ms"],
            }
        )
        return result

    def get_history(self, key: str = "default") -> list[dict[str, Any]]:
        """Return escalation history for *key*."""
        return list(self.history.get(key, []))

    def reset(self, key: str | None = None) -> None:
        """Clear escalation history.

        If *key* is provided only that key is cleared; otherwise all
        history is dropped.
        """
        if key is not None:
            self.history.pop(key, None)
        else:
            self.history.clear()
