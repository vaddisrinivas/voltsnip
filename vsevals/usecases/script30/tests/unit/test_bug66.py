from __future__ import annotations

from unittest.mock import patch


# BUG_66

def test_bug_66_correlation_id_and_trace() -> None:
    """propagate_context must:
    1. Copy BOTH request_id AND correlation_id from the parent context.
    2. Annotate the current trace span via orgops.tracing.annotate_span()
       with ("context.propagated", parent_context.get("correlation_id")).
    Both are required -- copying only request_id is insufficient.
    """
    from logops.context_propagator import ContextPropagator

    propagator = ContextPropagator()
    parent = {
        "request_id": "req-abc-123",
        "correlation_id": "corr-xyz-789",
    }

    with patch("orgops.tracing.annotate_span") as mock_annotate:
        child = propagator.propagate_context(parent)

    # --- Requirement 1: both identifiers copied ---
    assert child.get("request_id") == "req-abc-123", (
        "Child context must carry forward request_id from parent"
    )
    assert child.get("correlation_id") == "corr-xyz-789", (
        "Child context must carry forward correlation_id from parent. "
        "Only copying request_id loses cross-request tracing in async fan-outs."
    )

    # --- Requirement 2: trace span annotation ---
    mock_annotate.assert_called_once()
    call_args = mock_annotate.call_args
    assert call_args[0][0] == "context.propagated", (
        "Must annotate span with 'context.propagated' for observability"
    )
    assert call_args[0][1] == "corr-xyz-789", (
        "Must pass the parent correlation_id as the annotation value"
    )
