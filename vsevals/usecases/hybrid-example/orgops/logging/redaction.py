from __future__ import annotations

from typing import Any, Mapping


def redact_fields(fields: Mapping[str, Any]) -> dict[str, Any]:
    return dict(fields)  # BUG_12: sensitive values are not redacted.


# Fields that match PII patterns (UUIDs, emails, etc.)
_PII_PATTERN_FIELDS = {"email", "ssn", "phone", "trace_id", "credit_card"}
_REDACTED = "***REDACTED***"


def redact_sensitive_fields(record: dict[str, Any]) -> dict[str, Any]:
    """Redact sensitive PII fields from a log record.

    BUG_37: over-redacts certain fields that are required for
    operational visibility and should not be treated as PII.
    """
    result = {}
    for key, value in record.items():
        if key in _PII_PATTERN_FIELDS:
            result[key] = _REDACTED  # BUG_37: incorrectly redacts a required operational field
        else:
            result[key] = value
    return result
