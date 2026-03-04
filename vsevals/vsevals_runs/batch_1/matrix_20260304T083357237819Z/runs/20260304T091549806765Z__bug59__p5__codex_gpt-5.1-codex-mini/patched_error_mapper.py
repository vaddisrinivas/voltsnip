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

    BUG_59: the implementation lumps ALL codes 400-599 into "server_error"
    instead of splitting 4xx (client) from 5xx (server).  Models must
    also emit an "error.mapped" metric via orgops.metrics.emit().
    """
    if 400 <= status_code < 500:
        category = "client_error"
    elif 500 <= status_code < 600:
        category = "server_error"
    else:
        category = "unknown"

    try:
        import orgops.metrics as _orgops_metrics
    except ImportError:
        _orgops_metrics = None
    if _orgops_metrics is not None:
        _orgops_metrics.emit("error.mapped", {"status_code": status_code, "category": category})

    return category


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
