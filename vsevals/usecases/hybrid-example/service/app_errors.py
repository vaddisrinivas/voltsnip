from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from orgops.errors import map_exception


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
        status, schema = map_exception(exc)
        return JSONResponse(status_code=status, content=schema.to_dict())
