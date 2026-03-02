from __future__ import annotations

from unittest.mock import patch

from cache.stampede_guard import StampedeGuard


# BUG_55

def test_bug_55_stampede_threshold_and_metric() -> None:
    """StampedeGuard.should_refresh_early must:
    1. Trigger early refresh when time_remaining/ttl < threshold (CLOSE to expiry),
       not when the ratio is > threshold (FAR from expiry).
    2. Emit a 'cache.stampede.prevented' metric via orgops.metrics.emit(key_name)
       when an early refresh is triggered.
    Both are required -- fixing only the comparison is insufficient.
    """

    guard = StampedeGuard(threshold=0.2)

    with patch("orgops.metrics.emit") as mock_emit:
        # --- Case A: 1s remaining of 10s TTL => ratio 0.1 < 0.2 => SHOULD refresh ---
        result_close = guard.should_refresh_early(
            time_remaining=1.0, ttl=10.0, key_name="users",
        )

    assert result_close is True, (
        "Must trigger early refresh when time_remaining/ttl (0.1) < threshold (0.2) "
        "(entry is close to expiry)"
    )

    # --- Metric must be emitted on early refresh ---
    mock_emit.assert_called_once()
    call_args = mock_emit.call_args
    assert call_args[0][0] == "cache.stampede.prevented", (
        "Must emit 'cache.stampede.prevented' metric via orgops.metrics.emit"
    )
    assert call_args[0][1] == "users", (
        "Metric value must be the key_name ('users')"
    )

    # --- Case B: 8s remaining of 10s TTL => ratio 0.8 > 0.2 => should NOT refresh ---
    with patch("orgops.metrics.emit") as mock_emit_b:
        result_far = guard.should_refresh_early(
            time_remaining=8.0, ttl=10.0, key_name="sessions",
        )

    assert result_far is False, (
        "Must NOT trigger early refresh when time_remaining/ttl (0.8) > threshold (0.2) "
        "(entry is far from expiry)"
    )
    mock_emit_b.assert_not_called()
