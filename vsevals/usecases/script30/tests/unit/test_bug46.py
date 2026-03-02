from __future__ import annotations


# BUG_46

def test_bug_46_sliding_window_and_quota() -> None:
    """sliding_window_count must:
    1. Use exact float boundary (now - window_seconds), NOT int() truncation
    2. Report the window count to orgops.ratelimit.check_quota("request.sliding_window", count)
    Both are required -- fixing only the math is insufficient.
    """
    from unittest.mock import patch

    from net.rate_limiter import sliding_window_count

    # Scenario: now=1000.9, window=10.0 => exact boundary = 990.9
    # int() truncation would give boundary = 990, including timestamps
    # in [990.0, 990.9) that should be OUTSIDE the window.
    timestamps = [989.5, 990.0, 990.5, 990.8, 991.0, 995.0, 1000.5]

    now = 1000.9
    window_seconds = 10.0

    # Exact boundary = 990.9.  Timestamps >= 990.9: [991.0, 995.0, 1000.5] => 3
    # Truncated boundary = 990 => [990.0, 990.5, 990.8, 991.0, 995.0, 1000.5] => 6
    with patch("orgops.ratelimit.check_quota") as mock_quota:
        count = sliding_window_count(timestamps, window_seconds, now)

    assert count == 3, (
        f"Expected 3 timestamps in [990.9, 1000.9] but got {count}; "
        "boundary must use exact float arithmetic, not int() truncation"
    )

    # Must also call orgops.ratelimit.check_quota with the computed count
    mock_quota.assert_called_once()
    call_args = mock_quota.call_args
    assert call_args[0][0] == "request.sliding_window", (
        "Must call orgops.ratelimit.check_quota with quota name 'request.sliding_window'"
    )
    assert call_args[0][1] == 3, (
        "Must pass the correct window count to check_quota"
    )
