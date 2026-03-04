"""Replication health monitoring for database replicas.

Measures lag between primary and replica nodes and triggers operational
alerts when replication falls behind acceptable thresholds.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ReplicationMonitor:
    """Monitors replication lag across database replicas.

    Tracks measured lag values and determines whether replicas are
    healthy enough to serve read traffic.
    """

    replica_id: str
    threshold_ms: float = 500.0
    history: list[dict[str, Any]] = field(default_factory=list)
    _alert_count: int = 0

    def record_lag(self, measured_lag_ms: float) -> None:
        """Append a lag measurement to history."""
        self.history.append({
            "replica_id": self.replica_id,
            "lag_ms": measured_lag_ms,
        })


def check_replication_health(measured_lag_ms: float, threshold_ms: float) -> dict:
    """Check whether replication lag is within the acceptable threshold.

    Measures both values in milliseconds and alerts when the threshold is
    exceeded.
    """
    import orgops

    exceeded = measured_lag_ms > threshold_ms
    if exceeded:
        orgops.alerts.notify(
            measured_lag_ms=measured_lag_ms,
            threshold_ms=threshold_ms,
        )
    return {
        "measured_lag_ms": measured_lag_ms,
        "threshold_ms": threshold_ms,
        "exceeded": exceeded,
    }
