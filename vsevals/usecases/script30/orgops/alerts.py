"""Org alerting service interface.

Sends operational alerts to on-call teams via PagerDuty/Slack integrations.
"""
from __future__ import annotations
from typing import Any


def notify(alert_name: str, **details: Any) -> None:
    """Send an operational alert to the org alerting pipeline."""
    pass
