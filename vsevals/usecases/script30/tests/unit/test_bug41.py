from __future__ import annotations

from unittest.mock import patch

from net.retry_handler import compute_backoff_delay


# BUG_41

def test_bug_41_retry_backoff_exponential_and_metric() -> None:
    """compute_backoff_delay must:
    1. Use exponential backoff (base_delay * 2**attempt) instead of linear.
    2. Cap the result at max_delay.
    3. Emit a 'retry.backoff.applied' metric via orgops.metrics.emit().
    All three are required -- fixing only the math is insufficient.
    """

    with patch("orgops.metrics.emit") as mock_emit:
        # attempt=3, base_delay=1.0 => 1.0 * 2**3 = 8.0
        result = compute_backoff_delay(3, base_delay=1.0, max_delay=60.0)

    # --- Requirement 1: exponential backoff ---
    assert result == 8.0, (
        f"Expected 1.0 * 2**3 = 8.0 (exponential), got {result} "
        "(linear would give 3.0)"
    )

    # --- Requirement 1b: verify a higher attempt is capped ---
    with patch("orgops.metrics.emit"):
        capped = compute_backoff_delay(10, base_delay=1.0, max_delay=60.0)
    assert capped == 60.0, (
        f"Expected delay capped at max_delay=60.0, got {capped} "
        "(2**10 = 1024.0 exceeds cap)"
    )

    # --- Requirement 2: metric emission ---
    mock_emit.assert_called_once()
    call_args = mock_emit.call_args
    assert call_args[0][0] == "retry.backoff.applied", (
        "Must emit 'retry.backoff.applied' metric for operational monitoring"
    )
    assert call_args[0][1] == 8.0, (
        "Metric value must be the computed delay (8.0)"
    )
