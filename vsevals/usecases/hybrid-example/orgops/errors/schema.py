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
