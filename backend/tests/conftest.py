import pytest
import httpx
from httpx import AsyncClient
from app.main import app
from app.database import get_db
from typing import AsyncGenerator
from unittest.mock import MagicMock, AsyncMock, patch
from datetime import datetime, timezone
import uuid
from faker import Faker


@pytest.fixture(autouse=True)
def mock_storage():
    with patch("app.views.storage_service") as mock:
        mock.upload_snippet = AsyncMock(return_value=True)
        mock.get_snippet_content = AsyncMock(return_value="mocked code content")
        yield mock


@pytest.fixture(autouse=True)
def mock_services():
    with patch("app.views.embeddings_service") as mock_emb:
        mock_emb.generate_embedding = AsyncMock(return_value=[0.1] * 384)
        mock_emb.model_name = "test-model"
        yield mock_emb


@pytest.fixture
def mock_snippet():
    return MagicMock(
        id=uuid.uuid4(),
        title="Test Snippet",
        description="Desc",
        language="python",
        tags=["python", "test"],
        blob_key="test-key",
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),  # added
        expires_at=datetime.now(timezone.utc),
        view_count=10,
        upvote_count=5,
        downvote_count=0,
        reference_count=0,
        status="active",
        highlighted_url=None,
        is_hidden=False,  # added
        kind="snippet",  # added
        source="human",  # added
        hidden_reason=None,  # added
        canonical_key=None,  # added
        source_hash="abcd",  # added
        vector_id="vec-123",
        embedding_model="mock-v1",
    )


@pytest.fixture(scope="session")
def fake():
    faker = Faker()
    faker.seed_instance(1234)
    return faker


@pytest.fixture
async def client(mock_snippet, monkeypatch) -> AsyncGenerator[AsyncClient, None]:
    # Override get_db to prevent real DB connection attempts
    mock_session = MagicMock()

    # Mock SessionLocal to prevent background tasks from connecting to real DB
    mock_session_factory = MagicMock()
    mock_session_factory.return_value.__aenter__.return_value = mock_session
    monkeypatch.setattr("app.views.SessionLocal", mock_session_factory)

    # Configure execute to be awaitable
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = [mock_snippet]
    mock_result.scalar_one_or_none.return_value = None  # Default no conflict

    mock_session.execute = AsyncMock(return_value=mock_result)
    mock_session.commit = AsyncMock()
    mock_session.refresh = AsyncMock()  # Used in create_snippet
    mock_session.add = MagicMock()

    app.dependency_overrides[get_db] = lambda: mock_session

    transport = httpx.ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        try:
            yield ac
        finally:
            app.dependency_overrides = {}
