from datetime import datetime, timedelta, timezone
import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from testcontainers.core.docker_client import DockerClient
from testcontainers.postgres import PostgresContainer

from app import crud
from app.constants import ACTIVE_STATUS, SURVIVED_STATUS, SURVIVAL_VIEWS
from app.database import Base
from app.models import Snippet, SnippetEmbedding, SnippetReference, Stats
from app.schemas import SnippetCreate

TEST_TABLES = [Snippet.__table__, Stats.__table__, SnippetReference.__table__]
EMBEDDING_TABLES = [Snippet.__table__, SnippetEmbedding.__table__]


def _async_url(url: str) -> str:
    for prefix in (
        "postgresql+psycopg2://",
        "postgresql+psycopg://",
        "postgresql+pg8000://",
    ):
        if url.startswith(prefix):
            return f"postgresql+asyncpg://{url[len(prefix):]}"
    if url.startswith("postgresql://"):
        return url.replace("postgresql://", "postgresql+asyncpg://", 1)
    if url.startswith("postgres://"):
        return url.replace("postgres://", "postgresql+asyncpg://", 1)
    return url


def _docker_available() -> bool:
    try:
        DockerClient().client.ping()
        return True
    except Exception:
        return False


@pytest.fixture(scope="session")
def postgres_container():
    if not _docker_available():
        pytest.skip("Docker not available for integration tests.")
    with PostgresContainer("pgvector/pgvector:pg16") as container:
        yield container


@pytest.fixture
async def db_session(postgres_container):
    async_url = _async_url(postgres_container.get_connection_url())
    engine = create_async_engine(async_url, future=True)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all, tables=TEST_TABLES)
    Session = async_sessionmaker(engine, expire_on_commit=False)
    async with Session() as session:
        yield session
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all, tables=TEST_TABLES)
    await engine.dispose()


@pytest.fixture
async def db_session_with_embeddings(postgres_container):
    async_url = _async_url(postgres_container.get_connection_url())
    engine = create_async_engine(async_url, future=True)
    async with engine.begin() as conn:
        try:
            await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        except Exception:
            await engine.dispose()
            pytest.skip("pgvector extension not available.")
        await conn.run_sync(Base.metadata.create_all, tables=EMBEDDING_TABLES)
    Session = async_sessionmaker(engine, expire_on_commit=False)
    async with Session() as session:
        yield session
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all, tables=EMBEDDING_TABLES)
    await engine.dispose()


async def _create_snippet(db_session, fake, **overrides):
    data = {
        "title": fake.sentence(nb_words=4),
        "code": "print('hello')",
        "language": "python",
        "tags": ["python", "testing"],
    }
    data.update(overrides)
    snippet = SnippetCreate(**data)
    return await crud.create_snippet(
        db_session,
        snippet,
        blob_key="snippets/demo.py",
        id=uuid.uuid4(),
        source_hash=uuid.uuid4().hex,
    )


def _vector_with_hot_index(index: int, size: int = 384) -> list[float]:
    vector = [0.0] * size
    vector[index] = 1.0
    return vector


@pytest.mark.integration
@pytest.mark.asyncio
async def test_crud_create_get_and_hash(db_session, fake):
    source_hash = uuid.uuid4().hex
    snippet = SnippetCreate(
        title=fake.sentence(nb_words=3),
        code="print('hi')",
        language="python",
        tags=["python"],
    )
    created = await crud.create_snippet(
        db_session,
        snippet,
        blob_key="snippets/create.py",
        id=uuid.uuid4(),
        source_hash=source_hash,
    )

    fetched = await crud.get_snippet(db_session, created.id)
    assert fetched is not None
    assert fetched.id == created.id

    by_hash = await crud.get_snippet_by_hash(
        db_session, source=created.source, source_hash=source_hash
    )
    assert by_hash is not None
    assert by_hash.id == created.id


@pytest.mark.integration
@pytest.mark.asyncio
@pytest.mark.parametrize("value, attr", [(1, "upvote_count"), (-1, "downvote_count")])
async def test_vote_and_view_updates_counts(db_session, fake, value, attr):
    created = await _create_snippet(db_session, fake)

    updated_vote = await crud.vote_snippet(db_session, created.id, value)
    assert getattr(updated_vote, attr) == 1

    updated_view = await crud.increment_view(db_session, created.id)
    assert updated_view.view_count == 1


@pytest.mark.integration
@pytest.mark.asyncio
async def test_survival_promotion_by_views(db_session, fake):
    created = await _create_snippet(db_session, fake)
    created.view_count = SURVIVAL_VIEWS - 1
    await db_session.commit()

    promoted = await crud.increment_view(db_session, created.id)

    assert promoted.status == SURVIVED_STATUS
    assert promoted.expires_at > datetime.now(timezone.utc) + timedelta(days=365 * 5)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_snippet_reference_versions(db_session, fake):
    parent = await _create_snippet(db_session, fake)
    child_a = await _create_snippet(db_session, fake)
    child_b = await _create_snippet(db_session, fake)

    ref1 = await crud.create_snippet_reference(db_session, parent.id, child_a.id)
    ref2 = await crud.create_snippet_reference(db_session, parent.id, child_b.id)

    assert ref1.version == 1
    assert ref2.version == 2


@pytest.mark.integration
@pytest.mark.asyncio
async def test_update_stats_upsert(db_session):
    await crud.update_stats(db_session, snippets=1, views=2, upvotes=3, downvotes=4)
    await crud.update_stats(db_session, snippets=2, views=1, upvotes=1, downvotes=0)

    stats = await crud.get_stats(db_session)
    assert stats.total_snippets == 3
    assert stats.total_views == 3
    assert stats.total_upvotes == 4
    assert stats.total_downvotes == 4


@pytest.mark.integration
@pytest.mark.asyncio
async def test_get_snippet_respects_visibility(db_session, fake):
    expired = await _create_snippet(db_session, fake)
    expired.status = ACTIVE_STATUS
    expired.expires_at = datetime.now(timezone.utc) - timedelta(hours=1)
    await db_session.commit()
    # Expiration is no longer part of active visibility filtering.
    assert await crud.get_snippet(db_session, expired.id) is not None

    hidden = await _create_snippet(db_session, fake)
    hidden.status = SURVIVED_STATUS
    hidden.is_hidden = True
    await db_session.commit()
    assert await crud.get_snippet(db_session, hidden.id) is None

    visible = await _create_snippet(db_session, fake)
    visible.status = SURVIVED_STATUS
    visible.is_hidden = False
    await db_session.commit()
    assert await crud.get_snippet(db_session, visible.id) is not None


@pytest.mark.integration
@pytest.mark.asyncio
async def test_semantic_search_orders_by_distance(db_session_with_embeddings, fake):
    snippet_a = await _create_snippet(
        db_session_with_embeddings,
        fake,
        title="alpha",
    )
    snippet_b = await _create_snippet(
        db_session_with_embeddings,
        fake,
        title="beta",
    )

    embedding_a = SnippetEmbedding(
        snippet_id=snippet_a.id,
        vector=_vector_with_hot_index(0),
        embedding_model="test",
    )
    embedding_b = SnippetEmbedding(
        snippet_id=snippet_b.id,
        vector=_vector_with_hot_index(1),
        embedding_model="test",
    )
    db_session_with_embeddings.add_all([embedding_a, embedding_b])
    await db_session_with_embeddings.commit()

    results = await crud.semantic_search_snippets(
        db_session_with_embeddings, query_vector=_vector_with_hot_index(0), k=2
    )
    assert results[0].id == snippet_a.id
