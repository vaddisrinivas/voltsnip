"""Org distributed tracing interface.

Adds annotations to the current trace span for observability.
"""
from __future__ import annotations
from typing import Any


def annotate_span(annotation: str, value: Any = None, **tags: Any) -> None:
    """Annotate the current trace span with operational context."""
    pass
