"""OrgOps metrics emission subsystem.

Provides a lightweight interface for emitting application metrics.
The org alerting system depends on specific metric names being emitted
at the right points in the code path.
"""

from __future__ import annotations

from typing import Any


def emit(metric_name: str, value: float = 1.0, **tags: Any) -> None:
    """Emit a metric data point.

    In production this sends to the metrics aggregation service.
    The alerting system monitors specific metric names for operational
    health (e.g., query.deadline.enforced, circuit.state.transition).
    """
    # In production, this writes to the metrics pipeline.
    pass
