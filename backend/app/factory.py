from fastapi import APIRouter, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import ORJSONResponse
from contextlib import asynccontextmanager
import logging
import sys

from fastmcp import FastMCP
from app.config import settings
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
)

mcp_app = None

def setup_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        handlers=[logging.StreamHandler(sys.stdout)],
    )
    logging.getLogger("botocore").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)


@asynccontextmanager
async def _noop_lifespan(_app: FastAPI):
    yield


@asynccontextmanager
async def app_lifespan(app: FastAPI):
    setup_logging()
    lifespan_ctx = mcp_app.lifespan(app) if mcp_app else _noop_lifespan(app)
    async with lifespan_ctx:
        yield


def create_app() -> FastAPI:
    global mcp_app

    app = FastAPI(
        title="VoltSnip HTTP API",
        version=getattr(settings, "VERSION", "0.1.0"),
        lifespan=app_lifespan,
        default_response_class=ORJSONResponse,
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
    )

    @app.middleware("http")
    async def verify_gateway_secret(request, call_next):
        if not settings.VOLTSNIP_GATEWAY_SECRET or request.url.path in ["/health", "/docs", "/openapi.json"]:
            return await call_next(request)
            
        secret = request.headers.get("X-Gateway-Secret")
        if secret != settings.VOLTSNIP_GATEWAY_SECRET:
            from fastapi.responses import JSONResponse
            return JSONResponse(
                status_code=403,
                content={"detail": "Direct access forbidden. Use the public API endpoint."}
            )
            
        return await call_next(request)

    if getattr(settings, "CORS_ORIGINS", None):
        allow_origins = settings.CORS_ORIGINS
        allow_credentials = True
        if "*" in allow_origins:
            allow_credentials = False

        app.add_middleware(
            CORSMiddleware,
            allow_origins=allow_origins,
            allow_credentials=allow_credentials,
            allow_methods=["*"],
            allow_headers=["*"],
        )

    api_router = APIRouter(prefix="/api/v1")

    feeds_router = APIRouter(prefix="/feeds", tags=["feeds"])
    feeds_router.get("/trending", response_model=List[SnippetMetaResponse])(trending_feed)
    feeds_router.get("/hot", response_model=List[SnippetMetaResponse])(hot_feed)
    feeds_router.get("/top", response_model=List[SnippetMetaResponse])(top_feed)
    feeds_router.get("/most-used", response_model=List[SnippetMetaResponse])(most_used_feed)
    api_router.include_router(feeds_router)

    search_router = APIRouter(prefix="/search", tags=["search"])
    search_router.get("/", response_model=List[SnippetMetaResponse])(search)
    search_router.get("/semantic", response_model=List[SnippetMetaResponse])(
        semantic_search
    )
    api_router.include_router(search_router)

    snippets_router = APIRouter(prefix="/snippets", tags=["snippets"])
    snippets_router.post("/", response_model=SnippetDetailResponse)(create_snippet)
    snippets_router.get("/{snippet_id}", response_model=SnippetDetailResponse)(read_snippet)
    snippets_router.post("/{snippet_id}/view", response_model=SnippetMetaResponse)(
        view_snippet
    )
    snippets_router.post("/{snippet_id}/vote", response_model=SnippetMetaResponse)(
        vote_snippet
    )
    api_router.include_router(snippets_router)

    app.include_router(api_router)

    mcp = FastMCP.from_fastapi(app)

    try:
        mcp_app = mcp.http_app(path="/")
        app.mount("/mcp", mcp_app)
        logging.getLogger(__name__).info("MCP mounted at /mcp")
    except Exception as e:
        mcp_app = None
        logging.getLogger(__name__).error(f"MCP mount failed: {e}")

    @app.get("/health", tags=["health"])
    def health_check():
        return {"status": "ok"}
    
    return app
