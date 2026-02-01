from fastapi import Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Optional
import uuid
import logging

from app.database import get_db
from app.schemas import SnippetCreate, Vote
from app.services import storage_service, embeddings_service
from app.config import settings
import app.crud as crud

logger = logging.getLogger(__name__)


async def trending_feed(
    limit: int = 50, offset: int = 0, db: AsyncSession = Depends(get_db)
):
    return await crud.get_trending_feed(db, limit, offset)


async def hot_feed(
    limit: int = 50, offset: int = 0, db: AsyncSession = Depends(get_db)
):
    return await crud.get_hot_feed(db, limit, offset)


async def top_feed(
    limit: int = 50, offset: int = 0, db: AsyncSession = Depends(get_db)
):
    return await crud.get_top_feed(db, limit, offset)


async def most_used_feed(
    limit: int = 50, offset: int = 0, db: AsyncSession = Depends(get_db)
):
    return await crud.get_most_used_feed(db, limit, offset)


async def search(
    tag: Optional[str] = None,
    language: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
    db: AsyncSession = Depends(get_db),
):
    return await crud.search_snippets(db, tag, language, limit, offset)


async def semantic_search(
    q: str = Query(..., min_length=1),
    k: int = Query(20, le=settings.MAX_SEARCH_K),
    db: AsyncSession = Depends(get_db),
):
    if not settings.EMBEDDINGS_ENABLED:
        raise HTTPException(
            status_code=503, detail="Semantic search is temporarily disabled."
        )

    query_vector = await embeddings_service.generate_embedding(q)
    return await crud.semantic_search_snippets(db, query_vector, k=k)


async def create_snippet(snippet: SnippetCreate, db: AsyncSession = Depends(get_db)):
    # Calculate source_hash for human snippet
    import hashlib

    normalized = f"{snippet.title}{snippet.description}{snippet.language}{''.join(sorted(snippet.tags))}{snippet.code}"
    source_hash = hashlib.sha256(normalized.encode("utf-8")).hexdigest()

    # Idempotency check
    existing = await crud.get_snippet_by_hash(db, "human", source_hash)
    if existing:
        content = await storage_service.get_snippet_content(existing.blob_key)
        existing.code = content
        return existing

    if len(snippet.code) > settings.MAX_CODE_SIZE:
        raise HTTPException(
            status_code=413,
            detail=f"Snippet content exceeds maximum size of {settings.MAX_CODE_SIZE} bytes.",
        )

    snippet_id = uuid.uuid4()
    blob_key = f"{snippet_id}.txt"
    embedding_model = embeddings_service.model_name
    vector = None

    if settings.EMBEDDINGS_ENABLED:
        try:
            # Limit context text for embedding to save costs/tokens
            context_text = f"{snippet.title or ''} {snippet.description or ''} {' '.join(snippet.tags)} {snippet.code[:1000]}"
            vector = await embeddings_service.generate_embedding(context_text)
        except Exception as e:
            logger.error(f"Vector generation failed for snippet: {e}")
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
        source="human",
        source_hash=source_hash,
    )

    # Upload code content to storage
    await storage_service.upload_snippet(blob_key, snippet.code)

    db_snippet.code = snippet.code
    return db_snippet


async def read_snippet(snippet_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    db_snippet = await crud.get_snippet(db, snippet_id)
    if not db_snippet:
        raise HTTPException(status_code=404, detail="Snippet not found")

    content = await storage_service.get_snippet_content(db_snippet.blob_key)
    db_snippet.code = content
    return db_snippet


async def view_snippet(snippet_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    db_snippet = await crud.increment_view(db, snippet_id)
    if not db_snippet:
        raise HTTPException(status_code=404, detail="Snippet not found")
    return db_snippet


async def vote_snippet(
    snippet_id: uuid.UUID, vote: Vote, db: AsyncSession = Depends(get_db)
):
    db_snippet = await crud.vote_snippet(db, snippet_id, vote.value)
    if not db_snippet:
        raise HTTPException(status_code=404, detail="Snippet not found")
    return db_snippet
