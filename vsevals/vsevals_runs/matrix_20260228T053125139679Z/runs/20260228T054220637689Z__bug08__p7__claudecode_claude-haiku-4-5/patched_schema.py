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
            "code": self.code,
            "message": self.message,
            "details": self.details,
            "trace_id": self.trace_id,
        }
