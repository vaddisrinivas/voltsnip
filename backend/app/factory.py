from fastapi import APIRouter, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import ORJSONResponse
from contextlib import asynccontextmanager
import logging
import sys

from fastmcp import FastMCP
from app.globals import settings
import app.globals as app_globals
import app.crud as crud
from app.schemas import SnippetDetailResponse, SnippetMetaResponse
from typing import List
from app.views import (
    create_snippet,
    hot_feed,
    most_used_feed,
    read_snippet,
    search,
    semantic_search,
    top_feed,
    trending_feed,
    view_snippet,
    vote_snippet,
    get_stats,
)
from app.constants import (
    API_PREFIX,
    FEEDS_PREFIX,
    SEARCH_PREFIX,
    SNIPPETS_PREFIX,
    STATS_PATH,
    HEALTH_PATH,
    MCP_PATH,
    DOCS_PATH,
    REDOC_PATH,
    OPENAPI_PATH,
    FEEDS_TRENDING_PATH,
    FEEDS_HOT_PATH,
    FEEDS_TOP_PATH,
    FEEDS_MOST_USED_PATH,
    SEARCH_ROOT_PATH,
    SEARCH_SEMANTIC_PATH,
    SNIPPETS_ROOT_PATH,
    SNIPPET_BY_ID_PATH,
    SNIPPET_VIEW_PATH,
    SNIPPET_VOTE_PATH,
    FEEDS_TAG,
    SEARCH_TAG,
    SNIPPETS_TAG,
    STATS_TAG,
    HEALTH_TAG,
    APP_TITLE,
    DEFAULT_APP_VERSION,
    MIDDLEWARE_HTTP,
    GATEWAY_SECRET_HEADER,
    GATEWAY_FORBIDDEN_DETAIL,
    HEALTH_STATUS_KEY,
    HEALTH_STATUS_OK,
    MCP_MOUNT_LOG,
    MCP_MOUNT_FAILED_LOG,
    MCP_INTERNAL_PATH,
    MCP_SNIPPETS_RESOURCE,
    MCP_SNIPPET_RESOURCE,
    MCP_SNIPPETS_BY_TAG_RESOURCE,
    MCP_SNIPPETS_BY_TITLE_RESOURCE,
    MCP_SNIPPETS_BY_LANGUAGE_RESOURCE,
    MCP_SNIPPET_INVALID_ID,
    MCP_SNIPPET_NOT_FOUND,
    MCP_INVALID_FILTER,
    SETTINGS_VERSION_ATTR,
    LOG_FORMAT,
    BOTOCORO_LOGGER_NAME,
    URLLIB3_LOGGER_NAME,
    SETTINGS_CORS_ORIGINS_ATTR,
    CORS_ALLOW_ALL,
    ALLOW_METHODS_ALL,
    ALLOW_HEADERS_ALL,
    ERROR_DETAIL_KEY,
)
from app.cache import get_cached_snippet, set_cached_snippet
import uuid

def setup_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format=LOG_FORMAT,
        handlers=[logging.StreamHandler(sys.stdout)],
    )
    logging.getLogger(BOTOCORO_LOGGER_NAME).setLevel(logging.WARNING)
    logging.getLogger(URLLIB3_LOGGER_NAME).setLevel(logging.WARNING)


@asynccontextmanager
async def _noop_lifespan(_app: FastAPI):
    yield


@asynccontextmanager
async def app_lifespan(app: FastAPI):
    setup_logging()
    lifespan_ctx = (
        app_globals.mcp_app.lifespan(app)
        if app_globals.mcp_app
        else _noop_lifespan(app)
    )
    async with lifespan_ctx:
        yield


def create_app() -> FastAPI:
    app = FastAPI(
        title=APP_TITLE,
        version=getattr(settings, SETTINGS_VERSION_ATTR, DEFAULT_APP_VERSION),
        lifespan=app_lifespan,
        default_response_class=ORJSONResponse,
        docs_url=DOCS_PATH,
        redoc_url=REDOC_PATH,
        openapi_url=OPENAPI_PATH,
    )

    @app.middleware(MIDDLEWARE_HTTP)
    async def verify_gateway_secret(request, call_next):
        if not settings.VOLTSNIP_GATEWAY_SECRET or request.url.path in [
            HEALTH_PATH,
            DOCS_PATH,
            OPENAPI_PATH,
        ]:
            return await call_next(request)
            
        secret = request.headers.get(GATEWAY_SECRET_HEADER)
        if secret != settings.VOLTSNIP_GATEWAY_SECRET:
            from fastapi.responses import JSONResponse
            return JSONResponse(
                status_code=403,
                content={ERROR_DETAIL_KEY: GATEWAY_FORBIDDEN_DETAIL}
            )
            
        return await call_next(request)

    if getattr(settings, SETTINGS_CORS_ORIGINS_ATTR, None):
        allow_origins = settings.CORS_ORIGINS
        allow_credentials = True
        if CORS_ALLOW_ALL in allow_origins:
            allow_credentials = False

        app.add_middleware(
            CORSMiddleware,
            allow_origins=allow_origins,
            allow_credentials=allow_credentials,
            allow_methods=ALLOW_METHODS_ALL,
            allow_headers=ALLOW_HEADERS_ALL,
        )

    api_router = APIRouter(prefix=API_PREFIX)

    feeds_router = APIRouter(prefix=FEEDS_PREFIX, tags=[FEEDS_TAG])
    feeds_router.get(FEEDS_TRENDING_PATH, response_model=List[SnippetMetaResponse])(trending_feed)
    feeds_router.get(FEEDS_HOT_PATH, response_model=List[SnippetMetaResponse])(hot_feed)
    feeds_router.get(FEEDS_TOP_PATH, response_model=List[SnippetMetaResponse])(top_feed)
    feeds_router.get(FEEDS_MOST_USED_PATH, response_model=List[SnippetMetaResponse])(most_used_feed)
    api_router.include_router(feeds_router)

    search_router = APIRouter(prefix=SEARCH_PREFIX, tags=[SEARCH_TAG])
    search_router.get(SEARCH_ROOT_PATH, response_model=List[SnippetMetaResponse])(search)
    search_router.get(SEARCH_SEMANTIC_PATH, response_model=List[SnippetMetaResponse])(
        semantic_search
    )
    api_router.include_router(search_router)

    snippets_router = APIRouter(prefix=SNIPPETS_PREFIX, tags=[SNIPPETS_TAG])
    snippets_router.post(SNIPPETS_ROOT_PATH, response_model=SnippetDetailResponse)(create_snippet)
    snippets_router.get(SNIPPET_BY_ID_PATH, response_model=SnippetDetailResponse)(read_snippet)
    snippets_router.post(SNIPPET_VIEW_PATH, response_model=SnippetMetaResponse)(
        view_snippet
    )
    snippets_router.post(SNIPPET_VOTE_PATH, response_model=SnippetMetaResponse)(
        vote_snippet
    )
    api_router.include_router(snippets_router)

    app.get(STATS_PATH, tags=[STATS_TAG])(get_stats)

    app.include_router(api_router)

    mcp = FastMCP.from_fastapi(app)

    @mcp.resource(MCP_SNIPPETS_RESOURCE)
    async def mcp_snippets():
        async with app_globals.SessionLocal() as session:
            snippets = await crud.get_recent_snippets(session, limit=50, offset=0)
            return [SnippetMetaResponse.model_validate(s).model_dump() for s in snippets]

    @mcp.resource(MCP_SNIPPETS_BY_TAG_RESOURCE)
    async def mcp_snippets_by_tag(tag: str):
        tag = (tag or "").strip().lower()
        if not tag:
            return {"error": MCP_INVALID_FILTER}
        tags = [t.strip().lower() for t in tag.split(",") if t.strip()]
        async with app_globals.SessionLocal() as session:
            snippets = await crud.search_snippets_by_tags(session, tags=tags, limit=50, offset=0)
            return [SnippetMetaResponse.model_validate(s).model_dump() for s in snippets]

    @mcp.resource(MCP_SNIPPETS_BY_TITLE_RESOURCE)
    async def mcp_snippets_by_title(title: str):
        title = (title or "").strip()
        if not title:
            return {"error": MCP_INVALID_FILTER}
        async with app_globals.SessionLocal() as session:
            snippets = await crud.search_snippets_by_title(session, title=title, limit=50, offset=0)
            return [SnippetMetaResponse.model_validate(s).model_dump() for s in snippets]

    @mcp.resource(MCP_SNIPPETS_BY_LANGUAGE_RESOURCE)
    async def mcp_snippets_by_language(language: str):
        language = (language or "").strip().lower()
        if not language:
            return {"error": MCP_INVALID_FILTER}
        async with app_globals.SessionLocal() as session:
            snippets = await crud.search_snippets(session, tag=None, language=language, limit=50, offset=0)
            return [SnippetMetaResponse.model_validate(s).model_dump() for s in snippets]

    @mcp.resource(MCP_SNIPPET_RESOURCE)
    async def mcp_snippet(snippet_id: str):
        try:
            snippet_uuid = uuid.UUID(snippet_id)
        except ValueError:
            return {"error": MCP_SNIPPET_INVALID_ID}

        cached = await get_cached_snippet(snippet_uuid)
        if cached is not None:
            return cached

        async with app_globals.SessionLocal() as session:
            snippet = await crud.get_snippet(session, snippet_uuid)
            if not snippet:
                return {"error": MCP_SNIPPET_NOT_FOUND}
            content = await app_globals.storage_service.get_snippet_content(snippet.blob_key)
            snippet.code = content
            payload = SnippetDetailResponse.model_validate(snippet).model_dump()
            await set_cached_snippet(
                snippet_uuid,
                payload,
                app_globals.settings.SNIPPET_CACHE_TTL_SECONDS,
            )
            return payload

    try:
        app_globals.mcp_app = mcp.http_app(path=MCP_INTERNAL_PATH)
        app.mount(MCP_PATH, app_globals.mcp_app)
        logging.getLogger(__name__).info(MCP_MOUNT_LOG, MCP_PATH)
    except Exception as e:
        app_globals.mcp_app = None
        logging.getLogger(__name__).error(MCP_MOUNT_FAILED_LOG, e)

    @app.get(HEALTH_PATH, tags=[HEALTH_TAG])
    def health_check():
        return {HEALTH_STATUS_KEY: HEALTH_STATUS_OK}
    
    return app
