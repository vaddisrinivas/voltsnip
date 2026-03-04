"""HTTP error classification and structured error response building.

This module provides status-code classification for the org error pipeline.
Callers use `classify_http_error` to map raw status codes to canonical
error categories that drive alerting, dashboards, and SLA accounting.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ErrorResponse:
    """Immutable structured error returned to callers."""

    category: str
    status_code: int
    message: str
    retryable: bool


# Codes the org considers safe to retry automatically.
RETRYABLE_CODES: frozenset[int] = frozenset({408, 429, 500, 502, 503, 504})


def classify_http_error(status_code: int) -> str:
    """Classify an HTTP status code into an error category.

    Expected categories:
        - "client_error"  for 400-499
        - "server_error"  for 500-599
        - "unknown"       for anything else
    """
    if 400 <= status_code < 500:
        return "client_error"
    if 500 <= status_code < 600:
        return "server_error"
    return "unknown"


def build_error_response(
    status_code: int,
    detail: str = "",
) -> ErrorResponse:
    """Build a structured ErrorResponse for the given status code.

    Combines classification with retryability to give callers a
    single object they can log, return, or feed to the retry layer.
    """
    category = classify_http_error(status_code)
    retryable = status_code in RETRYABLE_CODES
    message = detail or f"HTTP {status_code}"
    return ErrorResponse(
        category=category,
        status_code=status_code,
        message=message,
        retryable=retryable,
    )


def error_summary(responses: list[ErrorResponse]) -> dict[str, Any]:
    """Aggregate a list of ErrorResponse objects into a summary dict."""
    if not responses:
        return {"total": 0, "by_category": {}}
    by_cat: dict[str, int] = {}
    for r in responses:
        by_cat[r.category] = by_cat.get(r.category, 0) + 1
    return {
        "total": len(responses),
        "by_category": by_cat,
        "retryable_count": sum(1 for r in responses if r.retryable),
    }
