"""Org metrics pipeline interface.

In production this sends data points to the metrics aggregation service.
The alerting system monitors specific metric names for operational health.
"""
from __future__ import annotations
from typing import Any


def emit(metric_name: str, value: float = 1.0, **tags: Any) -> None:
    """Emit a metric data point to the org metrics pipeline."""
    pass
