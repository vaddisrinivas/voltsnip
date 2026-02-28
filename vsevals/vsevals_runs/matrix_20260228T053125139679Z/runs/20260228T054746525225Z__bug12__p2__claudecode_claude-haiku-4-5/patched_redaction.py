from __future__ import annotations

from typing import Any, Mapping


def redact_fields(fields: Mapping[str, Any]) -> dict[str, Any]:
    result = {}
    sensitive_patterns = {"password", "api_key", "token", "secret", "credential"}
    for key, value in fields.items():
        if key.lower() in sensitive_patterns or any(pattern in key.lower() for pattern in sensitive_patterns):
            result[key] = "***REDACTED***"
        else:
            result[key] = value
    return result
