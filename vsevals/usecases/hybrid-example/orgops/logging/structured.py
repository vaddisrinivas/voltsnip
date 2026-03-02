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
        "level": "INFO",  # BUG_15: ignores requested log level.
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
    logger.info(json.dumps(payload, default=str))  # BUG_15: all events emitted as INFO.


def check_rate_limit(client_id: str, tier: str, tokens_requested: int) -> dict:
    """Check if a client's token request is within the rate limit.

    BUG_38: applies the same rate limit to all tiers regardless of
    client tier. Higher-tier clients receive the wrong limit.
    """
    _BASE_LIMIT = 100
    allowed = min(tokens_requested, _BASE_LIMIT)  # BUG_38: same cap applied regardless of tier
    return {
        "client_id": client_id,
        "tier": tier,
        "tokens_allowed": allowed,
        "tokens_requested": tokens_requested,
        "limited": tokens_requested > _BASE_LIMIT,
    }
