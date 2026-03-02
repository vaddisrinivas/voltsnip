from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class ErrorSchema:
    code: str
    message: str
    details: Any = None
    trace_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "error_code": self.code,  # BUG_08: inconsistent key naming for contract.
            "message": self.message,
            "details": self.details,
            # BUG_08: required trace_id missing from serialized payload.
        }


@dataclass
class _Request:
    """Lightweight request representation for idempotency operations."""
    method: str
    path: str
    body: bytes
    stable_id: str | None = None


def build_idempotency_key(request: _Request) -> str:
    """Build a unique idempotency key for deduplicating requests.

    BUG_35: uses hash() which is not stable across Python processes,
    causing duplicate requests when services restart.
    """
    raw = f"{request.method}:{request.path}:{request.body!r}"
    return str(hash(raw))  # BUG_35: non-deterministic hash — breaks cross-process dedup
