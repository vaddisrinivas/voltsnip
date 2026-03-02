from __future__ import annotations

from fastapi import FastAPI

from service.app_config import external_api_key, external_base_url, stats_cache_ttl_seconds
from service.app_errors import register_exception_handlers
from service.app_http import make_http_client
from service.app_lifecycle import register_shutdown
from service.app_middleware import register_correlation_middleware
from service.app_routes_enrich import register_enrich_routes
from service.app_routes_users import register_user_routes
from service.cache import TTLCache
from service.db import build_engine, create_session_factory, init_schema, seed_data


def create_app(database_url: str | None = None) -> FastAPI:
    app = FastAPI(title="Hybrid OrgOps Toy Service")

    engine = build_engine(database_url)
    session_factory = create_session_factory(engine)
    init_schema(engine)
    seed_data(session_factory)

    app.state.session_factory = session_factory
    app.state.http_client = make_http_client()
    app.state.stats_cache = TTLCache(ttl_seconds=stats_cache_ttl_seconds())
    app.state.external_base_url = external_base_url()
    app.state.external_api_key = external_api_key()

    register_correlation_middleware(app)
    register_exception_handlers(app)
    register_user_routes(app)
    register_enrich_routes(app)
    register_shutdown(app)
    return app


app = create_app()
