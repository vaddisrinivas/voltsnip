from fastapi import Depends, HTTPException, Query, BackgroundTasks, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Optional
import uuid

from app.database import get_db, SessionLocal
from app.schemas import SnippetCreate, Vote, SnippetDetailResponse
from app.globals import storage_service, embeddings_service, stats_cache, feed_cache, logger
from app.globals import settings
import app.crud as crud
from app.cache import (
    increment_stat,
    initialize_stats,
    get_all_stats,
    get_cached_snippet,
    set_cached_snippet,
    update_cached_snippet,
)
from app.constants import (
    KEY_SNIPPETS,
    KEY_VIEWS,
    KEY_UPVOTES,
    KEY_DOWNVOTES,
    ERR_SEMANTIC_SEARCH_DISABLED,
    ERR_SNIPPET_NOT_FOUND,
    ERR_SNIPPET_TOO_LARGE,
    ERR_UPLOAD_FAILED,
    LOG_UPDATE_STATS_FAILED,
    LOG_VECTOR_GENERATION_FAILED,
    LOG_UPLOAD_FAILED,
    BLOB_KEY_TEMPLATE,
    SNIPPET_SOURCE_DEFAULT,
    ENCODING_UTF8,
    EMPTY_STRING,
    SPACE,
    CONTEXT_SNIPPET_MAX_CHARS,
    FEED_CACHE_KEY_TEMPLATE,
    FEEDS_TRENDING_PATH,
    FEEDS_HOT_PATH,
    FEEDS_TOP_PATH,
    FEEDS_MOST_USED_PATH,
)
import hashlib

async def _get_cached_feed(cache_key: str, ttl_seconds: int, fetcher):
    cached = await feed_cache.get(cache_key)
    if cached is not None:
        return cached
    data = await fetcher()
    await feed_cache.set(cache_key, data, ttl=ttl_seconds)
    return data


async def trending_feed(
    limit: int = 50, offset: int = 0, db: AsyncSession = Depends(get_db)
):
    # Get the trending snippets feed.
    cache_key = FEED_CACHE_KEY_TEMPLATE % (FEEDS_TRENDING_PATH, limit, offset)
    return await _get_cached_feed(
        cache_key,
        settings.FEED_CACHE_TTL_SECONDS,
        lambda: crud.get_trending_feed(db, limit, offset),
    )


async def hot_feed(
    limit: int = 50, offset: int = 0, db: AsyncSession = Depends(get_db)
):
    # Get the hot snippets feed (high engagement recently).
    cache_key = FEED_CACHE_KEY_TEMPLATE % (FEEDS_HOT_PATH, limit, offset)
    return await _get_cached_feed(
        cache_key,
        settings.FEED_CACHE_TTL_SECONDS,
        lambda: crud.get_hot_feed(db, limit, offset),
    )


async def top_feed(
    limit: int = 50, offset: int = 0, db: AsyncSession = Depends(get_db)
):
    # Get the top-rated snippets of all time.
    cache_key = FEED_CACHE_KEY_TEMPLATE % (FEEDS_TOP_PATH, limit, offset)
    return await _get_cached_feed(
        cache_key,
        settings.FEED_CACHE_TTL_SECONDS,
        lambda: crud.get_top_feed(db, limit, offset),
    )


async def most_used_feed(
    limit: int = 50, offset: int = 0, db: AsyncSession = Depends(get_db)
):
    # Get the most referenced/used snippets.
    cache_key = FEED_CACHE_KEY_TEMPLATE % (FEEDS_MOST_USED_PATH, limit, offset)
    return await _get_cached_feed(
        cache_key,
        settings.FEED_CACHE_TTL_SECONDS,
        lambda: crud.get_most_used_feed(db, limit, offset),
    )


async def search(
    tag: Optional[str] = None,
    language: Optional[str] = None,
    title: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
    db: AsyncSession = Depends(get_db),
):
    # Search snippets by tag or language.
    return await crud.search_snippets(db, tag, language, title, limit, offset)


async def semantic_search(
    q: str = Query(..., min_length=1),
    k: int = Query(20, le=settings.MAX_SEARCH_K),
    db: AsyncSession = Depends(get_db),
):
    # Search snippets semantically using vector embeddings.
    if not settings.EMBEDDINGS_ENABLED:
        raise HTTPException(
            status_code=503, detail=ERR_SEMANTIC_SEARCH_DISABLED
        )

    query_vector = await embeddings_service.generate_embedding(q)
    return await crud.semantic_search_snippets(db, query_vector, k=k)


async def _update_stats_async(
    snippets: int = 0,
    views: int = 0,
    upvotes: int = 0,
    downvotes: int = 0,
    db: AsyncSession | None = None,
):
    # Update stats in cache and DB inline/async.
    if not settings.STATS_ENABLED:
        return
    if snippets:
        await increment_stat(KEY_SNIPPETS, snippets)
    if views:
        await increment_stat(KEY_VIEWS, views)
    if upvotes:
        await increment_stat(KEY_UPVOTES, upvotes)
    if downvotes:
        await increment_stat(KEY_DOWNVOTES, downvotes)

    try:
        # Prefer the current request DB session when available.
        if db is None:
            async with SessionLocal() as session:
                await crud.update_stats(
                    session,
                    snippets=snippets,
                    views=views,
                    upvotes=upvotes,
                    downvotes=downvotes,
                )
        else:
            await crud.update_stats(
                db, snippets=snippets, views=views, upvotes=upvotes, downvotes=downvotes
            )
    except Exception as e:
        logger.error(LOG_UPDATE_STATS_FAILED, e)


def _snippet_cache_payload(snippet) -> dict:
    return SnippetDetailResponse.model_validate(snippet).model_dump()


def _compute_snippet_etag(snippet_id: uuid.UUID, updated_at) -> str:
    if hasattr(updated_at, "isoformat"):
        updated_value = updated_at.isoformat()
    else:
        updated_value = str(updated_at or "")
    payload = f"{snippet_id}:{updated_value}"
    return f"\"{hashlib.sha256(payload.encode(ENCODING_UTF8)).hexdigest()}\""


def _set_snippet_cache_headers(response: Response, etag: str) -> None:
    response.headers["ETag"] = etag
    response.headers["Cache-Control"] = f"public, max-age={settings.SNIPPET_CACHE_MAX_AGE_SECONDS}"


async def get_stats(db: AsyncSession = Depends(get_db)):
    # Get global statistics.
    if not settings.STATS_ENABLED:
        return {
            KEY_SNIPPETS: 0,
            KEY_VIEWS: 0,
            KEY_UPVOTES: 0,
            KEY_DOWNVOTES: 0,
        }
    # Check if a key exists to see if initialized (simplified)
    if await stats_cache.get(KEY_SNIPPETS) is None:
        db_stats = await crud.get_stats(db)
        await initialize_stats({
            KEY_SNIPPETS: db_stats.total_snippets,
            KEY_VIEWS: db_stats.total_views,
            KEY_UPVOTES: db_stats.total_upvotes,
            KEY_DOWNVOTES: db_stats.total_downvotes,
        })
    return await get_all_stats()


async def create_snippet(
    snippet: SnippetCreate,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
    # Create a new code snippet.
    import hashlib

    if snippet.parent_id:
        parent = await crud.get_snippet(db, snippet.parent_id)
        if not parent:
            raise HTTPException(status_code=404, detail=ERR_SNIPPET_NOT_FOUND)

    normalized_parts = [
        snippet.title or EMPTY_STRING,
        snippet.description or EMPTY_STRING,
        snippet.language or EMPTY_STRING,
        EMPTY_STRING.join(sorted(snippet.tags)),
        snippet.code,
    ]
    normalized = EMPTY_STRING.join(normalized_parts)
    source_hash = hashlib.sha256(normalized.encode(ENCODING_UTF8)).hexdigest()

    existing = await crud.get_snippet_by_hash(
        db, snippet.source or SNIPPET_SOURCE_DEFAULT, source_hash
    )
    if existing:
        content = await storage_service.get_snippet_content(existing.blob_key)
        existing.code = content
        await set_cached_snippet(
            existing.id,
            _snippet_cache_payload(existing),
            settings.SNIPPET_CACHE_TTL_SECONDS,
        )
        return existing

    if len(snippet.code) > settings.MAX_CODE_SIZE:
        raise HTTPException(
            status_code=413,
            detail=ERR_SNIPPET_TOO_LARGE % settings.MAX_CODE_SIZE,
        )

    snippet_id = uuid.uuid4()
    blob_key = BLOB_KEY_TEMPLATE % snippet_id
    embedding_model = embeddings_service.model_name
    vector = None

    if settings.EMBEDDINGS_ENABLED:
        try:
            context_parts = [
                snippet.title or EMPTY_STRING,
                snippet.description or EMPTY_STRING,
                SPACE.join(snippet.tags),
                snippet.code[:CONTEXT_SNIPPET_MAX_CHARS],
            ]
            context_text = SPACE.join(context_parts).strip()
            vector = await embeddings_service.generate_embedding(context_text)
        except Exception as e:
            logger.error(LOG_VECTOR_GENERATION_FAILED, e)
            embedding_model = None
    else:
        embedding_model = None

    db_snippet = await crud.create_snippet(
        db,
        snippet,
        blob_key,
        id=snippet_id,
        vector=vector,
        embedding_model=embedding_model,
        source=snippet.source or SNIPPET_SOURCE_DEFAULT,
        source_hash=source_hash,
    )

    metadata = None
    upload_success = await storage_service.upload_snippet(
        blob_key, snippet.code, metadata=metadata
    )
    if not upload_success:
        logger.error(LOG_UPLOAD_FAILED, snippet_id)
        raise HTTPException(status_code=500, detail=ERR_UPLOAD_FAILED)

    await _update_stats_async(snippets=1, db=db)
    if snippet.parent_id:
        await crud.create_snippet_reference(db, snippet.parent_id, db_snippet.id)
    db_snippet.code = snippet.code
    await set_cached_snippet(
        db_snippet.id,
        _snippet_cache_payload(db_snippet),
        settings.SNIPPET_CACHE_TTL_SECONDS,
    )
    return db_snippet


async def read_snippet(
    snippet_id: uuid.UUID,
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
):
    # Retrieve a snippet by ID.
    cached = await get_cached_snippet(snippet_id)
    if cached is not None:
        etag = _compute_snippet_etag(snippet_id, cached.get("updated_at"))
        if request.headers.get("if-none-match") == etag:
            return Response(
                status_code=304,
                headers={
                    "ETag": etag,
                    "Cache-Control": f"public, max-age={settings.SNIPPET_CACHE_MAX_AGE_SECONDS}",
                },
            )
        _set_snippet_cache_headers(response, etag)
        return cached
    db_snippet = await crud.get_snippet(db, snippet_id)
    if not db_snippet:
        raise HTTPException(status_code=404, detail=ERR_SNIPPET_NOT_FOUND)

    content = await storage_service.get_snippet_content(db_snippet.blob_key)
    db_snippet.code = content
    etag = _compute_snippet_etag(snippet_id, db_snippet.updated_at)
    if request.headers.get("if-none-match") == etag:
        return Response(
            status_code=304,
            headers={
                "ETag": etag,
                "Cache-Control": f"public, max-age={settings.SNIPPET_CACHE_MAX_AGE_SECONDS}",
            },
        )
    _set_snippet_cache_headers(response, etag)
    await set_cached_snippet(
        db_snippet.id,
        _snippet_cache_payload(db_snippet),
        settings.SNIPPET_CACHE_TTL_SECONDS,
    )
    return db_snippet


async def view_snippet(
    snippet_id: uuid.UUID,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
    # Increment the view count for a snippet.
    db_snippet = await crud.increment_view(db, snippet_id)
    if not db_snippet:
        raise HTTPException(status_code=404, detail=ERR_SNIPPET_NOT_FOUND)
    await _update_stats_async(views=1, db=db)
    await update_cached_snippet(
        snippet_id,
        settings.SNIPPET_CACHE_TTL_SECONDS,
        view_count=db_snippet.view_count,
        upvote_count=db_snippet.upvote_count,
        downvote_count=db_snippet.downvote_count,
        status=db_snippet.status,
        expires_at=db_snippet.expires_at,
        updated_at=db_snippet.updated_at,
    )
    return db_snippet


async def vote_snippet(
    snippet_id: uuid.UUID,
    vote: Vote,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
    # Vote on a snippet (upvote or downvote).
    db_snippet = await crud.vote_snippet(db, snippet_id, vote.value)
    if not db_snippet:
        raise HTTPException(status_code=404, detail=ERR_SNIPPET_NOT_FOUND)

    if vote.value > 0:
        await _update_stats_async(upvotes=1, db=db)
    else:
        await _update_stats_async(downvotes=1, db=db)

    await update_cached_snippet(
        snippet_id,
        settings.SNIPPET_CACHE_TTL_SECONDS,
        view_count=db_snippet.view_count,
        upvote_count=db_snippet.upvote_count,
        downvote_count=db_snippet.downvote_count,
        status=db_snippet.status,
        expires_at=db_snippet.expires_at,
        updated_at=db_snippet.updated_at,
    )

    return db_snippet
