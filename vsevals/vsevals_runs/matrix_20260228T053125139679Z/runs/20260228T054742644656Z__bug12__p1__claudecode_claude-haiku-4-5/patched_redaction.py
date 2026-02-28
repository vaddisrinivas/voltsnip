from __future__ import annotations

from typing import Any, Mapping


def redact_fields(fields: Mapping[str, Any]) -> dict[str, Any]:
    sensitive_keywords = {"password", "token", "api_key", "secret", "credentials", "auth"}
    result = {}
    for key, value in fields.items():
        if any(keyword in key.lower() for keyword in sensitive_keywords):
            result[key] = "***REDACTED***"
        else:
            result[key] = value
    return result
