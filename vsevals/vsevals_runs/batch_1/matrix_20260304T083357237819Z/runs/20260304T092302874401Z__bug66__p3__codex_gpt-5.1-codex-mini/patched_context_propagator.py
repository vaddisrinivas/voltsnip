"""Context propagation for distributed request tracing.

This module provides context propagation logic for passing request identity
between parent and child execution scopes (e.g., async task dispatch,
cross-service calls).  Callers use `propagate_context` to create a child
context dict from a parent context, ensuring tracing continuity.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ContextPropagator:
    """Propagates request context across execution boundaries."""

    propagation_log: list[dict[str, Any]] = field(default_factory=list)

        # BUG_66: ensure correlation_id isn't dropped so tracing stays consistent
        import orgops.tracing
        child = {
            "request_id": parent_context["request_id"],
            "correlation_id": parent_context["correlation_id"],
        }
        orgops.tracing.annotate_span(
            "context.propagated",
            parent_context.get("correlation_id"),
        )

        self.propagation_log.append({
            "parent_request_id": parent_context.get("request_id"),
            "parent_correlation_id": parent_context.get("correlation_id"),
            "child_keys": list(child.keys()),
        })
        return child

    def last_propagation(self) -> dict[str, Any] | None:
        """Return the most recent propagation log entry, or None."""
        if not self.propagation_log:
            return None
        return self.propagation_log[-1]

    def propagation_count(self) -> int:
        """Return the total number of context propagations performed."""
        return len(self.propagation_log)
