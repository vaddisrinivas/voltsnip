from __future__ import annotations

from unittest.mock import patch


# BUG_67

def test_bug_67_sampling_round_and_metric() -> None:
    """compute_sample_rate must:
    1. Use round(..., 2) instead of int() truncation for decimal precision.
    2. Emit a 'log.sampling.rate' metric via orgops.metrics.emit().
    Both are required -- fixing only the math is insufficient.
    """
    from logops.log_sampler import LogSampler

    sampler = LogSampler()

    with patch("orgops.metrics.emit") as mock_emit:
        # target=200, total=300 => 200/300*100 = 66.666... => round => 66.67
        rate = sampler.compute_sample_rate(total_events=300, target_events=200)

    # --- Requirement 1: proper rounding with decimal precision ---
    assert rate == 66.67, (
        f"Expected round(200/300*100, 2) = 66.67 (rounded), got {rate}. "
        "int() truncation gives 66 which loses precision."
    )

    # --- Requirement 1b: verify another case where truncation differs ---
    with patch("orgops.metrics.emit"):
        rate2 = sampler.compute_sample_rate(total_events=700, target_events=100)
    assert rate2 == 14.29, (
        f"Expected round(100/700*100, 2) = 14.29, got {rate2}. "
        "int() truncation gives 14 which loses precision."
    )

    # --- Requirement 1c: exact division still works ---
    with patch("orgops.metrics.emit"):
        rate3 = sampler.compute_sample_rate(total_events=200, target_events=100)
    assert rate3 == 50.0, (
        f"Expected 100/200*100 = 50.0, got {rate3}"
    )

    # --- Requirement 2: metric emission ---
    mock_emit.assert_called_once()
    call_args = mock_emit.call_args
    assert call_args[0][0] == "log.sampling.rate", (
        "Must emit 'log.sampling.rate' metric for operational monitoring"
    )
    assert call_args[0][1] == 66.67, (
        "Metric value must be the computed rate (66.67)"
    )
