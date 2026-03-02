from __future__ import annotations

from unittest.mock import patch

from errors.retry_budget import RetryBudget


# BUG_61

def test_bug_61_retry_budget_reset_and_metric() -> None:
    """RetryBudget.record_outcome must:
    1. Replenish remaining on success: min(remaining + 1, max_budget).
    2. Emit 'retry.budget.consumed' metric via orgops.metrics.emit() on every call.
    Both are required -- fixing only the decrement logic is insufficient.
    """

    budget = RetryBudget(max_budget=5)

    # --- Consume two tokens via failures ---
    with patch("orgops.metrics.emit") as mock_emit:
        budget.record_outcome(success=False)

    assert budget.remaining == 4, (
        f"Expected remaining=4 after one failure, got {budget.remaining}"
    )
    mock_emit.assert_called_once()
    assert mock_emit.call_args[0][0] == "retry.budget.consumed", (
        "Must emit 'retry.budget.consumed' metric on failure"
    )
    assert mock_emit.call_args[0][1] == 4, (
        f"Metric value must be the remaining budget (4), got {mock_emit.call_args[0][1]}"
    )

    with patch("orgops.metrics.emit"):
        budget.record_outcome(success=False)
    assert budget.remaining == 3, (
        f"Expected remaining=3 after two failures, got {budget.remaining}"
    )

    # --- Requirement 1: replenish on success ---
    with patch("orgops.metrics.emit") as mock_emit_success:
        budget.record_outcome(success=True)

    assert budget.remaining == 4, (
        f"Expected remaining=4 after one success replenishment, got {budget.remaining} "
        "(success must replenish: min(remaining + 1, max_budget))"
    )

    # --- Requirement 1b: replenish must cap at max_budget ---
    budget_full = RetryBudget(max_budget=3, remaining=3)
    with patch("orgops.metrics.emit"):
        budget_full.record_outcome(success=True)
    assert budget_full.remaining == 3, (
        f"Expected remaining capped at max_budget=3, got {budget_full.remaining}"
    )

    # --- Requirement 2: metric emission on success path ---
    mock_emit_success.assert_called_once()
    assert mock_emit_success.call_args[0][0] == "retry.budget.consumed", (
        "Must emit 'retry.budget.consumed' metric on success"
    )
    assert mock_emit_success.call_args[0][1] == 4, (
        f"Metric value must be the remaining budget (4), got {mock_emit_success.call_args[0][1]}"
    )
