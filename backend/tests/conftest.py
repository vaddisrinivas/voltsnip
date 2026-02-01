import pytest
from httpx import AsyncClient, ASGITransport
from app.main import app
from app.database import get_db
from typing import AsyncGenerator
from unittest.mock import MagicMock, AsyncMock
from datetime import datetime, timezone
import uuid


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


@pytest.fixture
async def client(mock_snippet) -> AsyncGenerator[AsyncClient, None]:
    # Override get_db to prevent real DB connection attempts
    mock_session = MagicMock()

    # Configure execute to be awaitable
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = [mock_snippet]
    mock_result.scalar_one_or_none.return_value = None  # Default no conflict

    mock_session.execute = AsyncMock(return_value=mock_result)
    mock_session.commit = AsyncMock()
    mock_session.refresh = AsyncMock()  # Used in create_snippet
    mock_session.add = MagicMock()

    app.dependency_overrides[get_db] = lambda: mock_session

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        yield ac

    app.dependency_overrides = {}
