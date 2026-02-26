from __future__ import annotations

from typing import Iterator

from fastapi import Request
from sqlalchemy.orm import Session

from orgops.db import session_scope
from orgops.http import OrgHTTPClient
from service.cache import TTLCache


def get_db(request: Request) -> Iterator[Session]:
    with session_scope(request.app.state.session_factory) as session:
        yield session


def get_http_client(request: Request) -> OrgHTTPClient:
    return request.app.state.http_client


def get_cache(request: Request) -> TTLCache:
    return request.app.state.stats_cache
