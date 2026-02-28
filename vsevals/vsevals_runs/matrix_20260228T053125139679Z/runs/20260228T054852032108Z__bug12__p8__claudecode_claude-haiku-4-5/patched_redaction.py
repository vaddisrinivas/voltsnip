from __future__ import annotations

from typing import Any, Mapping


def redact_fields(fields: Mapping[str, Any]) -> dict[str, Any]:
    redacted = {}
    sensitive_keys = {'password', 'token', 'api_key', 'secret', 'credential'}
    for key, value in fields.items():
        if any(sensitive in key.lower() for sensitive in sensitive_keys):
            redacted[key] = "***REDACTED***"
        else:
            redacted[key] = value
    return redacted
