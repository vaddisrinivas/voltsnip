from __future__ import annotations

from aiocache import SimpleMemoryCache
from typing import Optional, TYPE_CHECKING
import logging
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from app.config import Settings
from app.constants import (
    VOLTSNIP_LOGGER_NAME,
    PRIVATE_ATTR_PREFIX,
    SSL_MODE_PARAM,
    NEONDB_HOST_MARKER,
    NEON_TECH_HOST_MARKER,
    QUERY_SEPARATOR,
    SSL_CONNECT_ARG_KEY,
    SSL_CONNECT_ARG_VALUE,
)


if TYPE_CHECKING:
    from app.services import StorageService, EmbeddingsService


logger = logging.getLogger(VOLTSNIP_LOGGER_NAME)
settings = Settings()
mcp_app = None


class _LazyStorageService:
    # Lazy-load StorageService to avoid network I/O at import time.

    _instance: Optional[StorageService] = None

    def _get(self) -> StorageService:
        if self._instance is None:
            from app.services import StorageService
            self._instance = StorageService()
        return self._instance

    def __getattr__(self, name):
        # Avoid instantiating during introspection/patching on private/dunder attrs.
        if name.startswith(PRIVATE_ATTR_PREFIX):
            raise AttributeError(name)
        return getattr(self._get(), name)


class _LazyEmbeddingsService:
    # Lazy-load EmbeddingsService to avoid work at import time.

    _instance: Optional[EmbeddingsService] = None

    def _get(self) -> EmbeddingsService:
        if self._instance is None:
            from app.services import EmbeddingsService
            self._instance = EmbeddingsService()
        return self._instance

    def __getattr__(self, name):
        if name.startswith(PRIVATE_ATTR_PREFIX):
            raise AttributeError(name)
        return getattr(self._get(), name)


storage_service = _LazyStorageService()
s3_service = storage_service
embeddings_service = _LazyEmbeddingsService()
stats_cache = SimpleMemoryCache()
feed_cache = SimpleMemoryCache()
snippet_cache = SimpleMemoryCache()

_db_url = settings.DATABASE_URL
if SSL_MODE_PARAM in _db_url:
    _db_url = _db_url.split(QUERY_SEPARATOR)[0]

_connect_args = {}
if NEONDB_HOST_MARKER in _db_url or NEON_TECH_HOST_MARKER in _db_url:
    _connect_args = {SSL_CONNECT_ARG_KEY: SSL_CONNECT_ARG_VALUE}

engine = create_async_engine(
    _db_url,
    echo=False,
    future=True,
    pool_pre_ping=True,
    pool_recycle=1800,
    connect_args=_connect_args,
)

SessionLocal = async_sessionmaker(
    bind=engine, class_=AsyncSession, expire_on_commit=False, autoflush=False
)
