from __future__ import annotations

from unittest.mock import patch

from data.query_planner import QueryPlanner


# BUG_50

def test_bug_50_join_cost_and_metric() -> None:
    """estimate_join_cost must:
    1. Apply selectivity exactly once: left_rows * right_rows * selectivity
       (NOT left_rows * right_rows * selectivity * selectivity).
    2. Emit a 'query.plan.estimated_cost' metric via orgops.metrics.emit().
    Both are required -- fixing only the math is insufficient.
    """
    planner = QueryPlanner()

    with patch("orgops.metrics.emit") as mock_emit:
        cost = planner.estimate_join_cost(
            left_rows=1000,
            right_rows=500,
            selectivity=0.1,
        )

    # --- Requirement 1: single selectivity application ---
    # Correct: 1000 * 500 * 0.1 = 50_000
    # Buggy:   1000 * 500 * 0.1 * 0.1 = 5_000  (double selectivity)
    assert cost == 50_000.0, (
        f"Expected 1000 * 500 * 0.1 = 50000.0 (single selectivity), got {cost} "
        "(double selectivity would give 5000.0)"
    )

    # --- Requirement 2: metric emission ---
    mock_emit.assert_called_once()
    call_args = mock_emit.call_args
    assert call_args[0][0] == "query.plan.estimated_cost", (
        "Must emit 'query.plan.estimated_cost' metric for the optimizer dashboard"
    )
    assert call_args[0][1] == 50_000.0, (
        "Metric value must be the computed cost (50000.0)"
    )
