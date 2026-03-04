"""Log sampler with configurable sampling rate computation.

This module provides sampling rate calculation for high-volume log pipelines.
Callers use `compute_sample_rate` to determine what percentage of events to
retain when total volume exceeds a target threshold.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class LogSampler:
    """Computes and tracks log sampling rates for volume control."""

    history: list[dict[str, Any]] = field(default_factory=list)

    def compute_sample_rate(
        self,
        total_events: int,
        target_events: int,
    ) -> float:
        """Compute the sampling rate as a percentage (0-100).

        Returns the percentage of events to retain so that roughly
        *target_events* survive out of *total_events*.

        BUG_67: uses int() truncation instead of round(), losing decimal
        precision.  For example target=200, total=300 yields 66 instead
        of the correct 66.67.  Should use round(..., 2) for proper
        rounding with two-decimal precision.
        """
        if total_events <= 0:
            return 0.0
        if target_events >= total_events:
            return 100.0

        rate = round(target_events / total_events * 100, 2)
        import orgops.metrics
        orgops.metrics.emit("log.sampling.rate", rate)
        self.history.append({
            "total_events": total_events,
            "target_events": target_events,
            "rate": rate,
        })
        return float(rate)

    def last_rate(self) -> float | None:
        """Return the most recently computed rate, or None."""
        if not self.history:
            return None
        return self.history[-1]["rate"]

    def average_rate(self) -> float:
        """Return the average sampling rate across all computations."""
        if not self.history:
            return 0.0
        return round(
            sum(entry["rate"] for entry in self.history) / len(self.history), 2
        )
