from __future__ import annotations

from fastapi import FastAPI


def register_shutdown(app: FastAPI) -> None:
    @app.on_event("shutdown")
    def close_http_client() -> None:
        app.state.http_client.client.close()
