from __future__ import annotations

import uuid
from collections.abc import Callable
from typing import Awaitable

from fastapi import FastAPI, Request, Response

from orgops.logging import set_request_id


def register_correlation_middleware(app: FastAPI) -> None:
    @app.middleware("http")
    async def correlation_middleware(
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        request_id = request.headers.get("x-request-id") or f"req-{uuid.uuid4().hex[:8]}"
        set_request_id(request_id)
        response = await call_next(request)
        response.headers["x-request-id"] = request_id
        set_request_id(None)
        return response
