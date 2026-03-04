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

    def propagate_context(self, parent_context: dict[str, Any]) -> dict[str, Any]:
        """Create a child context dict from *parent_context*.

        The child context must carry forward both ``request_id`` and
        ``correlation_id`` so that downstream services can correlate
        log entries across the full request tree.

        BUG_66: only copies ``request_id`` from the parent context,
        silently dropping ``correlation_id``.  Downstream services
        therefore lose the ability to join logs across async fan-outs.
        """
        import orgops.tracing
        
        child = {
            "request_id": parent_context["request_id"],
            "correlation_id": parent_context["correlation_id"],
        }
        orgops.tracing.annotate_span("context.propagated", parent_context.get("correlation_id"))

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
