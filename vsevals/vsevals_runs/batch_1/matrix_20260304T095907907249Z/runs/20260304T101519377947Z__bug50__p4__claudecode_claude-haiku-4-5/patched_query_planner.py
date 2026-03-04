"""Query planner with cost estimation for join operations.

This module provides cardinality estimation and cost modelling for the
query execution engine.  The optimizer calls `estimate_join_cost` to
choose between nested-loop, hash, and merge join strategies.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Sequence


@dataclass(frozen=True)
class JoinStats:
    """Immutable statistics for a single join estimation."""

    left_rows: int
    right_rows: int
    selectivity: float
    estimated_cost: float


class QueryPlanner:
    """Estimates query costs and selects execution strategies."""

    def __init__(self, *, cost_per_row: float = 0.01) -> None:
        self.cost_per_row = cost_per_row
        self._history: list[JoinStats] = []

    # ------------------------------------------------------------------
    # Cost estimation
    # ------------------------------------------------------------------

    def estimate_join_cost(
        self,
        left_rows: int,
        right_rows: int,
        selectivity: float,
    ) -> float:
        """Estimate the output cardinality for a join operation.

        The formula is:  left_rows * right_rows * selectivity

        BUG_50: selectivity is applied twice, inflating the cost estimate
        and causing the optimizer to reject valid hash-join plans.
        """
        cost = left_rows * right_rows * selectivity
        self._history.append(
            JoinStats(
                left_rows=left_rows,
                right_rows=right_rows,
                selectivity=selectivity,
                estimated_cost=cost,
            )
        )
        import logging
        logging.getLogger("metrics").info("query.plan.estimated_cost", extra={"value": cost})
        return cost

    # ------------------------------------------------------------------
    # Strategy selection
    # ------------------------------------------------------------------

    def select_strategy(
        self,
        left_rows: int,
        right_rows: int,
        selectivity: float,
    ) -> str:
        """Return the recommended join strategy based on estimated cost."""
        cost = self.estimate_join_cost(left_rows, right_rows, selectivity)
        if cost < 1000:
            return "nested_loop"
        elif cost < 100_000:
            return "hash_join"
        return "merge_join"

    # ------------------------------------------------------------------
    # History helpers
    # ------------------------------------------------------------------

    def history(self) -> Sequence[JoinStats]:
        """Return immutable view of estimation history."""
        return tuple(self._history)

    def last_estimate(self) -> float | None:
        """Return the most recent estimated cost, or None."""
        if not self._history:
            return None
        return self._history[-1].estimated_cost

    def reset(self) -> None:
        """Clear estimation history."""
        self._history.clear()
