from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy import update, func, or_
from typing import List
from datetime import datetime, timezone, timedelta
import uuid

from app.models import Snippet, SnippetEmbedding
from app.schemas import SnippetCreate
from app.config import settings

ACTIVE_STATUS = "active"
SURVIVED_STATUS = "survived"
SURVIVAL_UPVOTES = 5
SURVIVAL_VIEWS = 50
SURVIVAL_REFERENCES = 3


def active_snippets_filter():
    """
    Filters snippets that are active or survived.
    Also ensures they haven't expired based on DB time.
    Also ensures they are not hidden.
    """
    return or_(
        (Snippet.status == SURVIVED_STATUS) & (Snippet.is_hidden.is_(False)),
        (Snippet.status == ACTIVE_STATUS)
        & (Snippet.expires_at > func.now())
        & (Snippet.is_hidden.is_(False)),
    )


async def create_snippet(
    db: AsyncSession,
    snippet: SnippetCreate,
    blob_key: str,
    id: uuid.UUID,
    vector: List[float] | None = None,
    embedding_model: str | None = None,
    source: str = "human",
    source_hash: str | None = None,
) -> Snippet:
    """
    Creates a new snippet in the database.
    source_hash is required for integrity but optional in signature to support migration,
    but application logic should provide it.
    However, for 'human' snippets, maybe we generate a hash too?
    Or nullable=True for human? The requirement was 'source_hash NOT NULL'.
    So we MUST provide one.
    """
    now = datetime.now(timezone.utc)
    # Fix TTL to 24h
    expires_at = now + timedelta(days=1)

    # If source_hash is missing (e.g. human via API), generate one from blob_key or similar
    # to satisfy NOT NULL constraint if not provided.
    if not source_hash:
        # Simple fallback hash for human content uniqueness based on ID/Key if absolutely needed
        # But realistically, human snippets might not strictly need content idempotency in the same way.
        # But DB requires it. We can hash the ID.
        import hashlib

        source_hash = hashlib.sha256(str(id).encode()).hexdigest()

    db_snippet = Snippet(
        id=id,
        title=snippet.title,
        description=snippet.description,
        language=snippet.language,
        tags=snippet.tags,
        kind=snippet.kind,
        canonical_key=snippet.canonical_key,
        blob_key=blob_key,
        created_at=now,
        updated_at=now,
        expires_at=expires_at,
        status=ACTIVE_STATUS,
        is_hidden=False,
        source=source,
        source_hash=source_hash,
    )
    db.add(db_snippet)

    if vector:
        db_embedding = SnippetEmbedding(
            snippet_id=id, vector=vector, embedding_model=embedding_model or "unknown"
        )
        db.add(db_embedding)

    await db.commit()
    await db.refresh(db_snippet)
    return db_snippet


async def get_snippet(db: AsyncSession, snippet_id: uuid.UUID) -> Snippet | None:
    query = (
        select(Snippet).where(Snippet.id == snippet_id).where(active_snippets_filter())
    )
    result = await db.execute(query)
    snippet = result.scalar_one_or_none()
    return snippet


async def increment_view(db: AsyncSession, snippet_id: uuid.UUID) -> Snippet | None:
    stmt = (
        update(Snippet)
        .where(Snippet.id == snippet_id)
        .where(active_snippets_filter())
        .values(view_count=Snippet.view_count + 1)
        .returning(Snippet)
    )
    result = await db.execute(stmt)
    updated_snippet = result.scalar_one_or_none()

    if updated_snippet:
        await check_survival(db, updated_snippet)

    await db.commit()
    if updated_snippet:
        await db.refresh(updated_snippet)
    return updated_snippet


async def vote_snippet(
    db: AsyncSession, snippet_id: uuid.UUID, value: int
) -> Snippet | None:
    values_to_update = {}
    if value > 0:
        values_to_update = {"upvote_count": Snippet.upvote_count + 1}
    else:
        values_to_update = {"downvote_count": Snippet.downvote_count + 1}

    stmt = (
        update(Snippet)
        .where(Snippet.id == snippet_id)
        .where(active_snippets_filter())
        .values(**values_to_update)
        .returning(Snippet)
    )
    result = await db.execute(stmt)
    updated_snippet = result.scalar_one_or_none()

    if updated_snippet:
        await check_survival(db, updated_snippet)

    await db.commit()
    if updated_snippet:
        await db.refresh(updated_snippet)
    return updated_snippet


async def check_survival(db: AsyncSession, snippet: Snippet):
    """
    Survival Logic:
    - If a snippet gets enough engagement (upvotes, views, references),
    - it is promoted to 'survived' status.
    - 'survived' snippets do not expire.
    """
    if snippet.status == "active":
        should_survive = (
            snippet.upvote_count >= SURVIVAL_UPVOTES
            or snippet.view_count >= SURVIVAL_VIEWS
            or snippet.reference_count >= SURVIVAL_REFERENCES
        )

        if should_survive:
            snippet.status = "survived"
            # Extending expiry just in case, though survived should ideally be infinite.
            # But keeping it consistent with 'no expire' logic in filter.
            snippet.expires_at = datetime.now(timezone.utc) + timedelta(days=365 * 10)
            db.add(snippet)


async def get_trending_feed(
    db: AsyncSession, limit: int = 50, offset: int = 0
) -> List[Snippet]:
    """
    Scoring Logic:
    - Heavily weighted on upvotes (2x)
    - Views contribute (0.5x)
    - Penalty for age (1 point per hour)
    """
    limit = min(limit, settings.MAX_SEARCH_K)  # Cap limit
    now_expr = func.now()
    age_in_hours = func.extract("EPOCH", now_expr - Snippet.created_at) / 3600.0
    score = (Snippet.upvote_count * 2 + Snippet.view_count * 0.5) - age_in_hours

    query = (
        select(Snippet)
        .where(active_snippets_filter())
        .where(
            Snippet.created_at
            > now_expr - timedelta(days=settings.TRENDING_WINDOW_DAYS)
        )  # Recent items optimization
        .order_by(score.desc())
        .limit(limit)
        .offset(offset)
    )
    result = await db.execute(query)
    return result.scalars().all()


async def get_hot_feed(
    db: AsyncSession, limit: int = 50, offset: int = 0
) -> List[Snippet]:
    limit = min(limit, 100)
    query = (
        select(Snippet)
        .where(active_snippets_filter())
        .order_by(
            Snippet.upvote_count.desc(),
            Snippet.view_count.desc(),
            Snippet.created_at.desc(),
        )
        .limit(limit)
        .offset(offset)
    )
    result = await db.execute(query)
    return result.scalars().all()


async def get_top_feed(
    db: AsyncSession, limit: int = 50, offset: int = 0
) -> List[Snippet]:
    limit = min(limit, 100)
    query = (
        select(Snippet)
        .where(Snippet.status == "survived")
        .where(Snippet.is_hidden.is_(False))
        .order_by(Snippet.upvote_count.desc())
        .limit(limit)
        .offset(offset)
    )
    result = await db.execute(query)
    return result.scalars().all()


async def get_most_used_feed(
    db: AsyncSession, limit: int = 50, offset: int = 0
) -> List[Snippet]:
    limit = min(limit, 100)
    query = (
        select(Snippet)
        .where(active_snippets_filter())
        .order_by(Snippet.reference_count.desc())
        .limit(limit)
        .offset(offset)
    )
    result = await db.execute(query)
    return result.scalars().all()


async def search_snippets(
    db: AsyncSession,
    tag: str | None = None,
    language: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> List[Snippet]:
    limit = min(limit, 100)
    query = select(Snippet).where(active_snippets_filter())

    if tag:
        query = query.where(Snippet.tags.contains([tag]))

    if language:
        query = query.where(Snippet.language == language)

    query = query.limit(limit).offset(offset)
    result = await db.execute(query)
    return result.scalars().all()


async def get_snippets_by_ids(
    db: AsyncSession, snippet_ids: List[uuid.UUID]
) -> List[Snippet]:
    if not snippet_ids:
        return []

    query = (
        select(Snippet)
        .where(Snippet.id.in_(snippet_ids))
        .where(active_snippets_filter())
    )
    result = await db.execute(query)
    snippets = result.scalars().all()

    snippet_map = {s.id: s for s in snippets}
    ordered = []
    for sid in snippet_ids:
        if sid in snippet_map:
            ordered.append(snippet_map[sid])
    return ordered


async def get_snippet_by_hash(
    db: AsyncSession, source: str, source_hash: str
) -> Snippet | None:
    query = select(Snippet).where(
        Snippet.source == source, Snippet.source_hash == source_hash
    )
    result = await db.execute(query)
    return result.scalar_one_or_none()


async def semantic_search_snippets(
    db: AsyncSession, query_vector: List[float], k: int = 10
) -> List[Snippet]:
    """
    Perform semantic search using pgvector cosine distance on the normalized SnippetEmbedding table.
    """
    k = min(k, 50)
    query = (
        select(Snippet)
        .join(SnippetEmbedding, Snippet.id == SnippetEmbedding.snippet_id)
        .where(active_snippets_filter())
        .order_by(SnippetEmbedding.vector.cosine_distance(query_vector))
        .limit(k)
    )
    result = await db.execute(query)
    return result.scalars().all()
