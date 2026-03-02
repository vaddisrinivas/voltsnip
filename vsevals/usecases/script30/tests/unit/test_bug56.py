from __future__ import annotations

from unittest.mock import patch

from cache.eviction_policy import LFUEvictionPolicy


# BUG_56

def test_bug_56_lfu_decay_and_metric() -> None:
    """compute_lfu_score must:
    1. Apply time decay: score = access_count / (1 + age_hours)
       (NOT raw access_count).
    2. Emit a 'cache.eviction.lfu' metric via orgops.metrics.emit().
    Both are required -- fixing only the math is insufficient.
    """

    policy = LFUEvictionPolicy()

    with patch("orgops.metrics.emit") as mock_emit:
        # access_count=100, age_hours=9 => 100 / (1 + 9) = 10.0
        result = policy.compute_lfu_score(100, age_hours=9.0)

    # --- Requirement 1: time-decay formula ---
    assert result == 10.0, (
        f"Expected 100 / (1 + 9) = 10.0 (time-decayed), got {result} "
        "(raw count would give 100.0)"
    )

    # --- Requirement 1b: verify fresh entry has higher score ---
    with patch("orgops.metrics.emit"):
        fresh = policy.compute_lfu_score(100, age_hours=0.0)
    assert fresh == 100.0, (
        f"Expected 100 / (1 + 0) = 100.0 for a fresh entry, got {fresh}"
    )

    # --- Requirement 2: metric emission ---
    mock_emit.assert_called_once()
    call_args = mock_emit.call_args
    assert call_args[0][0] == "cache.eviction.lfu", (
        "Must emit 'cache.eviction.lfu' metric for operational monitoring"
    )
    assert call_args[0][1] == 10.0, (
        "Metric value must be the computed score (10.0)"
    )
