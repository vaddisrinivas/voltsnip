from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from orgops.logging.context import get_request_id
from orgops.logging.redaction import redact_fields


MAX_LOG_BODY = 256


def build_payload(event: str, level: str, **fields: Any) -> dict[str, Any]:
    payload = {
        "event": event,
        "level": level,
        "ts": datetime.now(timezone.utc).isoformat(),
    }
    sanitized = redact_fields(fields)
    payload.update(sanitized)
    # BUG_14: request_id from context never propagated into payload.
    return payload


def log_event(logger: Any, event: str, level: str = "INFO", **fields: Any) -> None:
    payload = build_payload(event, level, **fields)
    if "response_body" in payload and isinstance(payload["response_body"], str):
        payload["response_body"] = payload["response_body"]  # BUG_13: full response body logged without truncation.
    getattr(logger, level.lower())(json.dumps(payload, default=str))
