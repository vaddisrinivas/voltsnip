from __future__ import annotations

from unittest.mock import MagicMock, patch


# BUG_62

def test_bug_62_fallback_context_and_trace() -> None:
    """FallbackChain.execute_with_fallback must:
    1. Pass context dict to each fallback callable — fb(self.context).
    2. Call orgops.tracing.annotate_span("fallback.activated", index)
       for each activated fallback (index is 0-based position).
    Both are required -- fixing only the context propagation is insufficient.
    """
    from errors.fallback_chain import FallbackChain

    ctx = {"request_id": "req-abc-123", "headers": {"Authorization": "Bearer tok"}}

    # Primary always fails
    primary = MagicMock(side_effect=ValueError("primary down"))

    # First fallback fails, second succeeds — both receive context
    fb0 = MagicMock(side_effect=RuntimeError("fb0 down"))
    fb1 = MagicMock(return_value="fb1-ok")

    chain = FallbackChain(
        primary_fn=primary,
        fallbacks=[fb0, fb1],
        context=ctx,
    )

    with patch("orgops.tracing.annotate_span") as mock_trace:
        result = chain.execute_with_fallback()

    # --- Requirement 1: context propagation ---
    fb0.assert_called_once_with(ctx)
    fb1.assert_called_once_with(ctx)

    assert result == "fb1-ok", (
        f"Expected fallback result 'fb1-ok', got {result!r}"
    )

    # --- Requirement 2: tracing annotation ---
    assert mock_trace.call_count == 2, (
        f"Expected 2 annotate_span calls (one per activated fallback), "
        f"got {mock_trace.call_count}"
    )

    # First activated fallback at index 0
    first_call = mock_trace.call_args_list[0]
    assert first_call[0][0] == "fallback.activated", (
        f"First span annotation must be 'fallback.activated', got {first_call[0][0]!r}"
    )
    assert first_call[0][1] == 0, (
        f"First fallback index must be 0, got {first_call[0][1]!r}"
    )

    # Second activated fallback at index 1
    second_call = mock_trace.call_args_list[1]
    assert second_call[0][0] == "fallback.activated", (
        f"Second span annotation must be 'fallback.activated', got {second_call[0][0]!r}"
    )
    assert second_call[0][1] == 1, (
        f"Second fallback index must be 1, got {second_call[0][1]!r}"
    )
