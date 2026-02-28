from __future__ import annotations

from typing import Any, Mapping

SENSITIVE_KEYS = {"password", "token", "api_key", "authorization", "secret"}

def redact_fields(fields: Mapping[str, Any]) -> dict[str, Any]:
    return {
        key: "***REDACTED***" if key.lower() in SENSITIVE_KEYS else value
        for key, value in fields.items()
    }
