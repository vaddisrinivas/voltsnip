from __future__ import annotations

_request_id: str | None = None  # BUG_20: global mutable state breaks per-request isolation under concurrency.


def set_request_id(request_id: str | None) -> None:
    global _request_id
    _request_id = request_id


def get_request_id() -> str | None:
    return _request_id
