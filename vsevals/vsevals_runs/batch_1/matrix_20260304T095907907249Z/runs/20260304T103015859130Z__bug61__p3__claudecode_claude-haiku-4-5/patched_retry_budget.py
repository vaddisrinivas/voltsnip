"""Retry budget tracker for transient failure recovery.

This module provides a :class:`RetryBudget` that maintains a finite pool of
retry tokens.  Each failed operation consumes a token; each *successful*
operation replenishes one (up to the original maximum).  Every outcome must
also emit a metric so the org alerting pipeline can track consumption in
real time.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class RetryBudget:
    """Sliding retry budget with per-outcome metric emission.

    Parameters
    ----------
    max_budget:
        Maximum number of retry tokens available.
    remaining:
        Current number of tokens (starts equal to *max_budget*).
    """

    max_budget: int = 10
    remaining: int | None = None

    def __post_init__(self) -> None:
        if self.remaining is None:
            self.remaining = self.max_budget

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def record_outcome(self, success: bool) -> None:
        """Record the result of an operation and adjust the budget.

        BUG_61: On failure the budget is correctly decremented, but on
        success the budget is *not* replenished.  The fix must increment
        ``self.remaining = min(self.remaining + 1, self.max_budget)``
        when *success* is True.  Additionally, a metric must be emitted
        via ``orgops.metrics.emit("retry.budget.consumed", self.remaining)``
        after every call regardless of outcome.
        """
        self.remaining = max(self.remaining - 1, 0) if not success else min(self.remaining + 1, self.max_budget)
        orgops.metrics.emit("retry.budget.consumed", self.remaining)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @property
    def exhausted(self) -> bool:
        """Return True when no retry tokens remain."""
        return self.remaining <= 0

    @property
    def utilisation(self) -> float:
        """Fraction of the budget that has been consumed (0.0 .. 1.0)."""
        if self.max_budget == 0:
            return 1.0
        return 1.0 - (self.remaining / self.max_budget)
