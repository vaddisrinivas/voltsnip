from __future__ import annotations

import threading

_local = threading.local()


def set_request_id(request_id: str | None) -> None:
    _local.request_id = request_id


def get_request_id() -> str | None:
    return getattr(_local, 'request_id', None)
