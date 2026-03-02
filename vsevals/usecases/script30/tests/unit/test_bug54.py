from __future__ import annotations

from unittest.mock import patch

from cache.ttl_manager import compute_ttl_with_jitter


# BUG_54

def test_bug_54_ttl_jitter_positive_and_metric() -> None:
    """compute_ttl_with_jitter must:
    1. Add jitter to base_ttl (not subtract), so the effective TTL is
       always >= base_ttl.
    2. Emit a 'cache.ttl.jittered' metric via orgops.metrics.emit()
       with the effective TTL value.
    Both are required -- fixing only the math is insufficient.
    """

    with patch("random.uniform", return_value=15.0):
        with patch("orgops.metrics.emit") as mock_emit:
            # base_ttl=300, jitter=15 => effective = 300 + 15 = 315
            result = compute_ttl_with_jitter(base_ttl=300.0, jitter_range=30.0)

    # --- Requirement 1: jitter is additive ---
    assert result == 315.0, (
        f"Expected 300.0 + 15.0 = 315.0 (additive jitter), got {result} "
        "(subtractive would give 285.0)"
    )

    # --- Requirement 1b: verify jitter never reduces TTL below base ---
    with patch("random.uniform", return_value=0.0):
        with patch("orgops.metrics.emit"):
            floor = compute_ttl_with_jitter(base_ttl=300.0, jitter_range=30.0)
    assert floor == 300.0, (
        f"With zero jitter the TTL should equal base_ttl=300.0, got {floor}"
    )

    # --- Requirement 2: metric emission ---
    mock_emit.assert_called_once()
    call_args = mock_emit.call_args
    assert call_args[0][0] == "cache.ttl.jittered", (
        "Must emit 'cache.ttl.jittered' metric for operational monitoring"
    )
    assert call_args[0][1] == 315.0, (
        "Metric value must be the effective TTL (315.0)"
    )
