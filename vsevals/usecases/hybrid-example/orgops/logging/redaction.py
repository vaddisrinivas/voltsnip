from __future__ import annotations

from typing import Any, Mapping


def redact_fields(fields: Mapping[str, Any]) -> dict[str, Any]:
    return dict(fields)  # BUG_12: sensitive values are not redacted.
