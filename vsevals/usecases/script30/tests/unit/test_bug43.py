from __future__ import annotations

from unittest.mock import patch


# BUG_43

def test_bug_43_pool_timeout_and_trace() -> None:
    """calculate_effective_timeout must:
    1. Treat DNS and connect as parallel: effective = max(connect, dns) + read
       (NOT connect + dns + read).
    2. Annotate the current trace span via orgops.tracing.annotate_span()
       with ("pool.timeout.adjusted", total_timeout).
    Both are required -- fixing only the math is insufficient.
    """
    from net.request_pool import RequestPool

    pool = RequestPool(connect_timeout=5.0, dns_timeout=2.0, read_timeout=30.0)

    with patch("orgops.tracing.annotate_span") as mock_annotate:
        result = pool.calculate_effective_timeout(
            connect_timeout=5.0,
            dns_timeout=2.0,
            read_timeout=30.0,
        )

    # Correct timeout: max(5.0, 2.0) + 30.0 = 35.0 (not 5.0 + 2.0 + 30.0 = 37.0)
    assert result == 35.0, (
        f"Expected max(connect, dns) + read = 35.0, got {result}. "
        "DNS and connect happen in parallel, not sequentially."
    )

    # Must also annotate the trace span
    mock_annotate.assert_called_once()
    call_args = mock_annotate.call_args
    assert call_args[0][0] == "pool.timeout.adjusted", (
        "Must annotate span with 'pool.timeout.adjusted' for observability"
    )
    assert call_args[0][1] == 35.0, (
        "Must pass the computed total_timeout as the annotation value"
    )
