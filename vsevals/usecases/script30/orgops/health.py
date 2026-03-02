"""Org service health reporting.

Reports degradation signals to the platform health dashboard.
"""
from __future__ import annotations
from typing import Any


def report_degradation(signal_name: str, value: Any = None, **tags: Any) -> None:
    """Report a service degradation signal to the org health system."""
    pass
