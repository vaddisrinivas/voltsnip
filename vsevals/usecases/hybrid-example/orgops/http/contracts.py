from __future__ import annotations

from typing import Protocol


class CircuitBreakerHook(Protocol):
    def allow_request(self) -> bool:
        ...

    def record_success(self) -> None:
        ...

    def record_failure(self) -> None:
        ...


class CircuitOpenError(RuntimeError):
    pass
