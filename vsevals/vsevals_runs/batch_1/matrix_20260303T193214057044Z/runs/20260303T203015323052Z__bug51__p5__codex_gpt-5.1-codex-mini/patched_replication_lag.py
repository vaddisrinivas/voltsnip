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


    exceeded = measured_lag_ms > threshold_ms
    if exceeded:
        import orgops
        orgops.alerts.notify("replication.lag.exceeded", lag_ms=measured_lag_ms)
