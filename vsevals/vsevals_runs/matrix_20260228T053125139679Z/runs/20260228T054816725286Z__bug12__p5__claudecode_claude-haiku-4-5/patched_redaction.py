from __future__ import annotations

from typing import Any, Mapping


def redact_fields(fields: Mapping[str, Any]) -> dict[str, Any]:
    return {key: '***REDACTED***' if any(s in key.lower() for s in ['password', 'token', 'api_key', 'secret']) else value for key, value in fields.items()}
