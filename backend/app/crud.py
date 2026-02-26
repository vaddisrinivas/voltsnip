from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy import update, func, or_
from sqlalchemy.dialects.postgresql import insert
from typing import List
from datetime import datetime, timezone, timedelta
import uuid

from app.models import Snippet, SnippetEmbedding, Stats, SnippetReference
from app.schemas import SnippetCreate
from app.globals import settings
from app.constants import (
    ACTIVE_STATUS,
    SNIPPET_SOURCE_DEFAULT,
    SURVIVED_STATUS,
    SURVIVAL_UPVOTES,
    SURVIVAL_VIEWS,
    SURVIVAL_REFERENCES,
    EMBEDDING_MODEL_UNKNOWN,
    EPOCH_EXTRACT_KEY,
    DEFAULT_STATS_ID,
)


def active_snippets_filter():
    return or_(
        (Snippet.status == SURVIVED_STATUS) & (Snippet.is_hidden.is_(False)),
        (Snippet.status == ACTIVE_STATUS) & (Snippet.is_hidden.is_(False)),
    )


def is_snippet_active(snippet: Snippet) -> bool:
    if snippet.is_hidden:
        return False
    return snippet.status in (SURVIVED_STATUS, ACTIVE_STATUS)


async def reactivate_snippet(db: AsyncSession, snippet: Snippet) -> Snippet:
    now = datetime.now(timezone.utc)
    snippet.status = ACTIVE_STATUS
    snippet.expires_at = now + timedelta(hours=settings.EXPIRATION_HOURS)
    snippet.is_hidden = False
    snippet.hidden_reason = None
    snippet.updated_at = now
    db.add(snippet)
    await db.commit()
    await db.refresh(snippet)
    return snippet


async def create_snippet(
    db: AsyncSession,
    snippet: SnippetCreate,
    blob_key: str,
    id: uuid.UUID,
    vector: List[float] | None = None,
    embedding_model: str | None = None,
    source: str = SNIPPET_SOURCE_DEFAULT,
    source_hash: str | None = None,
) -> Snippet:
    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(hours=settings.EXPIRATION_HOURS)

    if not source_hash:
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
        view_count=0,
        upvote_count=0,
        downvote_count=0,
        reference_count=0,
    )
    db.add(db_snippet)

    if vector:
        db_embedding = SnippetEmbedding(
            snippet_id=id,
            vector=vector,
            embedding_model=embedding_model or EMBEDDING_MODEL_UNKNOWN,
        )
        db.add(db_embedding)

    await db.commit()
    await db.refresh(db_snippet)
    return db_snippet


async def get_next_reference_version(
    db: AsyncSession, parent_id: uuid.UUID
) -> int:
    query = select(func.coalesce(func.max(SnippetReference.version), 0) + 1).where(
        SnippetReference.parent_id == parent_id
    )
    result = await db.execute(query)
    return int(result.scalar_one())


async def create_snippet_reference(
    db: AsyncSession, parent_id: uuid.UUID, child_id: uuid.UUID
) -> SnippetReference:
    version = await get_next_reference_version(db, parent_id)
    ref = SnippetReference(parent_id=parent_id, child_id=child_id, version=version)
    db.add(ref)
    await db.commit()
    await db.refresh(ref)
    return ref


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
        values_to_update = {Snippet.upvote_count: Snippet.upvote_count + 1}
    else:
        values_to_update = {Snippet.downvote_count: Snippet.downvote_count + 1}

    stmt = (
        update(Snippet)
        .where(Snippet.id == snippet_id)
        .where(active_snippets_filter())
        .values(values_to_update)
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
    if snippet.status == ACTIVE_STATUS:
        should_survive = (
            snippet.upvote_count >= SURVIVAL_UPVOTES
            or snippet.view_count >= SURVIVAL_VIEWS
            or snippet.reference_count >= SURVIVAL_REFERENCES
        )

        if should_survive:
            snippet.status = SURVIVED_STATUS
            snippet.expires_at = datetime.now(timezone.utc) + timedelta(days=365 * 10)
            db.add(snippet)


async def get_trending_feed(
    db: AsyncSession, limit: int = 50, offset: int = 0
) -> List[Snippet]:
    limit = min(limit, settings.MAX_SEARCH_K)
    now_expr = func.now()
    age_in_hours = func.extract(EPOCH_EXTRACT_KEY, now_expr - Snippet.created_at) / 3600.0
    score = (Snippet.upvote_count * 2 + Snippet.view_count * 0.5) - age_in_hours

    query = (
        select(Snippet)
        .where(active_snippets_filter())
        .where(
            Snippet.created_at
            > now_expr - timedelta(hours=settings.TRENDING_WINDOW_HOURS)
        )
        .order_by(score.desc())
        .limit(limit)
        .offset(offset)
    )
    result = await db.execute(query)
    return result.scalars().all()


async def get_recent_snippets(
    db: AsyncSession, limit: int = 50, offset: int = 0
) -> List[Snippet]:
    limit = min(limit, settings.MAX_SEARCH_K)
    query = (
        select(Snippet)
        .where(active_snippets_filter())
        .order_by(Snippet.created_at.desc())
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
        .where(Snippet.status == SURVIVED_STATUS)
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
    title: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> List[Snippet]:
    limit = min(limit, 100)
    query = select(Snippet).where(active_snippets_filter())

    if tag:
        query = query.where(Snippet.tags.contains([tag]))

    if language:
        query = query.where(Snippet.language == language)

    if title:
        query = query.where(Snippet.title.ilike(f"%{title}%"))

    query = query.limit(limit).offset(offset)
    result = await db.execute(query)
    return result.scalars().all()


async def search_snippets_by_title(
    db: AsyncSession,
    title: str,
    limit: int = 50,
    offset: int = 0,
) -> List[Snippet]:
    if not title:
        return []
    limit = min(limit, 100)
    query = (
        select(Snippet)
        .where(active_snippets_filter())
        .where(Snippet.title.ilike(f"%{title}%"))
        .limit(limit)
        .offset(offset)
    )
    result = await db.execute(query)
    return result.scalars().all()


async def search_snippets_by_tags(
    db: AsyncSession,
    tags: List[str],
    limit: int = 50,
    offset: int = 0,
) -> List[Snippet]:
    if not tags:
        return []
    limit = min(limit, 100)
    query = select(Snippet).where(active_snippets_filter())
    for tag in tags:
        query = query.where(Snippet.tags.contains([tag]))
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


async def upsert_snippet_embedding(
    db: AsyncSession,
    snippet_id: uuid.UUID,
    vector: List[float],
    embedding_model: str | None = None,
) -> None:
    query = (
        select(SnippetEmbedding)
        .where(SnippetEmbedding.snippet_id == snippet_id)
        .limit(1)
    )
    result = await db.execute(query)
    existing = result.scalar_one_or_none()
    if existing:
        existing.vector = vector
        existing.embedding_model = embedding_model or EMBEDDING_MODEL_UNKNOWN
        db.add(existing)
    else:
        db.add(
            SnippetEmbedding(
                snippet_id=snippet_id,
                vector=vector,
                embedding_model=embedding_model or EMBEDDING_MODEL_UNKNOWN,
            )
        )
    await db.commit()


async def get_snippet_by_canonical_key(
    db: AsyncSession, canonical_key: str
) -> Snippet | None:
    query = (
        select(Snippet)
        .where(active_snippets_filter())
        .where(Snippet.canonical_key == canonical_key)
        .order_by(Snippet.updated_at.desc())
        .limit(1)
    )
    result = await db.execute(query)
    return result.scalar_one_or_none()


async def semantic_search_snippets(
    db: AsyncSession, query_vector: List[float], k: int = 10
) -> List[Snippet]:
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


async def get_stats(db: AsyncSession) -> Stats:
    query = select(Stats).where(Stats.id == DEFAULT_STATS_ID)
    result = await db.execute(query)
    stats = result.scalar_one_or_none()
    if not stats:
        stats = Stats(
            id=DEFAULT_STATS_ID,
            total_snippets=0,
            total_views=0,
            total_upvotes=0,
            total_downvotes=0,
        )
        db.add(stats)
        await db.commit()
        await db.refresh(stats)
    return stats


async def update_stats(
    db: AsyncSession,
    snippets: int = 0,
    views: int = 0,
    upvotes: int = 0,
    downvotes: int = 0,
):
    stmt = (
        insert(Stats)
        .values(
            {
                Stats.id: DEFAULT_STATS_ID,
                Stats.total_snippets: snippets,
                Stats.total_views: views,
                Stats.total_upvotes: upvotes,
                Stats.total_downvotes: downvotes,
            }
        )
        .on_conflict_do_update(
            index_elements=[Stats.id],
            set_={
                Stats.total_snippets: Stats.total_snippets + snippets,
                Stats.total_views: Stats.total_views + views,
                Stats.total_upvotes: Stats.total_upvotes + upvotes,
                Stats.total_downvotes: Stats.total_downvotes + downvotes,
            },
        )
    )
    await db.execute(stmt)
    await db.commit()
