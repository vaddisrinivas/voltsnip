from fastapi import Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Optional
import uuid
import logging

from app.database import get_db
from app.schemas import SnippetCreate, Vote
from app.globals import storage_service, embeddings_service
from app.config import settings
import app.crud as crud

logger = logging.getLogger(__name__)


async def trending_feed(
    limit: int = 50, offset: int = 0, db: AsyncSession = Depends(get_db)
):
    """Get the trending snippets feed."""
    return await crud.get_trending_feed(db, limit, offset)


async def hot_feed(
    limit: int = 50, offset: int = 0, db: AsyncSession = Depends(get_db)
):
    """Get the hot snippets feed (high engagement recently)."""
    return await crud.get_hot_feed(db, limit, offset)


async def top_feed(
    limit: int = 50, offset: int = 0, db: AsyncSession = Depends(get_db)
):
    """Get the top-rated snippets of all time."""
    return await crud.get_top_feed(db, limit, offset)


async def most_used_feed(
    limit: int = 50, offset: int = 0, db: AsyncSession = Depends(get_db)
):
    """Get the most referenced/used snippets."""
    return await crud.get_most_used_feed(db, limit, offset)


async def search(
    tag: Optional[str] = None,
    language: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
    db: AsyncSession = Depends(get_db),
):
    """Search snippets by tag or language."""
    return await crud.search_snippets(db, tag, language, limit, offset)


async def semantic_search(
    q: str = Query(..., min_length=1),
    k: int = Query(20, le=settings.MAX_SEARCH_K),
    db: AsyncSession = Depends(get_db),
):
    """Search snippets semantically using vector embeddings."""
    if not settings.EMBEDDINGS_ENABLED:
        raise HTTPException(
            status_code=503, detail="Semantic search is temporarily disabled."
        )

    query_vector = await embeddings_service.generate_embedding(q)
    return await crud.semantic_search_snippets(db, query_vector, k=k)


async def create_snippet(snippet: SnippetCreate, db: AsyncSession = Depends(get_db)):
    """Create a new code snippet."""
    import hashlib

    normalized = f"{snippet.title}{snippet.description}{snippet.language}{''.join(sorted(snippet.tags))}{snippet.code}"
    source_hash = hashlib.sha256(normalized.encode("utf-8")).hexdigest()

    existing = await crud.get_snippet_by_hash(db, snippet.source or "human", source_hash)
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
        source=snippet.source or "human",
        source_hash=source_hash,
    )

    upload_success = await storage_service.upload_snippet(blob_key, snippet.code)
    if not upload_success:
        logger.error(f"Failed to upload snippet {snippet_id} to storage.")
        raise HTTPException(status_code=500, detail="Failed to upload snippet content to storage.")

    db_snippet.code = snippet.code
    return db_snippet


async def read_snippet(snippet_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    """Retrieve a snippet by ID."""
    db_snippet = await crud.get_snippet(db, snippet_id)
    if not db_snippet:
        raise HTTPException(status_code=404, detail="Snippet not found")

    content = await storage_service.get_snippet_content(db_snippet.blob_key)
    db_snippet.code = content
    return db_snippet


async def view_snippet(snippet_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    """Increment the view count for a snippet."""
    db_snippet = await crud.increment_view(db, snippet_id)
    if not db_snippet:
        raise HTTPException(status_code=404, detail="Snippet not found")
    return db_snippet


async def vote_snippet(
    snippet_id: uuid.UUID, vote: Vote, db: AsyncSession = Depends(get_db)
):
    """Vote on a snippet (upvote or downvote)."""
    db_snippet = await crud.vote_snippet(db, snippet_id, vote.value)
    if not db_snippet:
        raise HTTPException(status_code=404, detail="Snippet not found")
    return db_snippet
