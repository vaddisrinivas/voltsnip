"""Audit trail entry creation for compliance and forensic analysis.

This module creates structured audit entries for every significant
system event.  Each entry records the event type, acting user, and a
timestamp.  Downstream consumers (SIEM, SOC2 dashboards) expect UTC
timestamps so that entries from multiple regions can be correlated
without timezone ambiguity.
"""
from __future__ import annotations

from datetime import datetime
from dataclasses import dataclass, field
from typing import Any


@dataclass
class AuditTrail:
    """Append-only audit log for compliance-critical events."""

    entries: list[dict[str, Any]] = field(default_factory=list)

    def create_audit_entry(
        self,
        event: str,
        user_id: str,
    ) -> dict[str, Any]:
        """Create a new audit entry and append it to the trail.

        Uses a UTC clock so entries from all regions remain comparable
        and records the compliance decision that the timestamp is UTC.
        """
        from datetime import timezone
        from orgops.compliance import record_decision

        ts = datetime.now(timezone.utc)
        entry: dict[str, Any] = {
            "event": event,
            "user_id": user_id,
            "timestamp": ts.isoformat(),
            "utc": True,
        }
        self.entries.append(entry)
        record_decision(
            "audit_entry_timestamp",
            {
                "event": event,
                "user_id": user_id,
                "timestamp": entry["timestamp"],
            },
        )
        return entry

    def get_entries(self, user_id: str | None = None) -> list[dict[str, Any]]:
        """Return entries, optionally filtered by user_id."""
        if user_id is None:
            return list(self.entries)
        return [e for e in self.entries if e["user_id"] == user_id]

    def count(self) -> int:
        """Return the total number of audit entries."""
        return len(self.entries)
