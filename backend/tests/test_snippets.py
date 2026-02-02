import pytest
import uuid
from datetime import datetime
from unittest.mock import MagicMock, AsyncMock, patch


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


@pytest.fixture(autouse=True)
def mock_crud(monkeypatch):
    mock = MagicMock()
    
    # Create a real-ish object for return values to satisfy Pydantic validation
    class MockSnippet:
        def __init__(self, **kwargs):
            self.id = uuid.uuid4()
            self.created_at = datetime.now()
            self.updated_at = datetime.now()
            self.view_count = 0
            self.upvote_count = 0
            self.downvote_count = 0
            self.reference_count = 0
            self.status = "active"
            self.is_hidden = False
            self.hidden_reason = None
            self.source = "human"
            self.title = None
            self.description = None
            self.language = None
            self.tags = []
            self.kind = "snippet"
            self.canonical_key = None
            self.highlighted_url = None
            self.blob_key = "test_blob_key"
            self.code = ""
            for k, v in kwargs.items():
                setattr(self, k, v)
            
            # Ensure source is string for validation
            if getattr(self, "source", None) is None:
                self.source = "human"

    async def _create(*args, **kwargs):
        # Handle positional args: db, snippet, blob_key, ...
        # args[0] might be 'self' if bound, but here it's a standalone function, 
        # so args[0] is db, args[1] is snippet (if not named).
        # Actually, when called on a mock, args[0] IS correct.
        snippet_obj = kwargs.get('snippet')
        if not snippet_obj and len(args) > 1:
            snippet_obj = args[1]
            
        data = snippet_obj.model_dump() if snippet_obj else {}
        return MockSnippet(**data)
    
    # We remove side_effects for getters so tests can set return_value
    # But we set a default return_value
    
    mock.create_snippet = AsyncMock(side_effect=_create)
    mock.get_snippet = AsyncMock(return_value=MockSnippet())
    mock.increment_view = AsyncMock(return_value=MockSnippet())
    mock.vote_snippet = AsyncMock(return_value=MockSnippet())
    
    default_list = [MockSnippet() for _ in range(5)]
    mock.get_trending_feed = AsyncMock(return_value=default_list)
    mock.get_hot_feed = AsyncMock(return_value=default_list)
    mock.get_top_feed = AsyncMock(return_value=default_list)
    mock.get_most_used_feed = AsyncMock(return_value=default_list)
    
    mock.search_snippets = AsyncMock(return_value=default_list)
    mock.semantic_search_snippets = AsyncMock(return_value=default_list)
    mock.get_snippet_by_hash = AsyncMock(return_value=None) 
    
    monkeypatch.setattr("app.views.crud", mock)
    return mock


@pytest.mark.asyncio
async def test_create_snippet(client, mock_crud, mock_snippet):
    mock_crud.create_snippet.return_value = mock_snippet

    response = await client.post(
        "/api/v1/snippets/",
        json={
            "title": "Test Snippet",
            "code": "print('hello')",
            "language": "python",
            "tags": ["python", "test"],
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert data["title"] == "Test Snippet"
    assert "code" in data


@pytest.mark.asyncio
async def test_get_snippet_found(client, mock_crud, mock_snippet):
    mock_crud.get_snippet.return_value = mock_snippet

    response = await client.get(f"/api/v1/snippets/{mock_snippet.id}")
    assert response.status_code == 200
    data = response.json()
    assert data["id"] == str(mock_snippet.id)
    assert "code" in data


@pytest.mark.asyncio
async def test_feeds(client, mock_crud, mock_snippet):
    mock_list = [mock_snippet for _ in range(5)]
    mock_crud.get_trending_feed.return_value = mock_list
    mock_crud.get_hot_feed.return_value = mock_list
    mock_crud.get_top_feed.return_value = mock_list

    response = await client.get("/api/v1/feeds/trending")
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 5
    assert "code" not in data[0]


@pytest.mark.asyncio
async def test_search(client, mock_crud, mock_snippet):
    mock_crud.search_snippets.return_value = [mock_snippet]

    response = await client.get("/api/v1/search/?tag=python")
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert "code" not in data[0]


@pytest.mark.asyncio
async def test_semantic_search(client, mock_crud, mock_snippet):
    mock_crud.semantic_search_snippets.return_value = [mock_snippet]

    response = await client.get("/api/v1/search/semantic?q=test")
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert "code" not in data[0]


@pytest.mark.asyncio
async def test_vote(client, mock_crud, mock_snippet):
    mock_crud.vote_snippet.return_value = mock_snippet

    response = await client.post(
        f"/api/v1/snippets/{mock_snippet.id}/vote", json={"value": 1}
    )
    assert response.status_code == 200
    data = response.json()
    # SnippetMetaResponse should not have code.
    # We verify this behavior.
    assert "code" not in data


@pytest.mark.asyncio
async def test_view(client, mock_crud, mock_snippet):
    mock_crud.increment_view.return_value = mock_snippet

    response = await client.post(f"/api/v1/snippets/{mock_snippet.id}/view")
    assert response.status_code == 200
    data = response.json()
    assert "code" not in data


@pytest.mark.asyncio
async def test_create_snippet_large_payload(client, mock_crud):
    from app.config import settings
    # Testing MAX_CODE_SIZE (1MB default)
    large_code = "A" * (settings.MAX_CODE_SIZE + 1)
    response = await client.post(
        "/api/v1/snippets/",
        json={"title": "Large Snippet", "code": large_code, "language": "python"},
    )
    assert response.status_code == 422
    # assert "content exceeds maximum size" in response.json()["detail"] # Message varies by pydantic


@pytest.mark.asyncio
async def test_gateway_secret_enforcement(client, mock_crud):
    from app.config import settings
    # Temporarily set secret
    original_secret = settings.VOLTSNIP_GATEWAY_SECRET
    settings.VOLTSNIP_GATEWAY_SECRET = "top-secret"
    try:
        # Request without secret should fail
        response = await client.get("/api/v1/feeds/trending")
        assert response.status_code == 403
        assert response.json()["detail"] == "Direct access forbidden. Use the public API endpoint."

        # Request with wrong secret should fail
        response = await client.get(
            "/api/v1/feeds/trending", headers={"X-Gateway-Secret": "wrong"}
        )
        assert response.status_code == 403

        # Request with correct secret should pass
        response = await client.get(
            "/api/v1/feeds/trending", headers={"X-Gateway-Secret": "top-secret"}
        )
        assert response.status_code == 200
    finally:
        settings.VOLTSNIP_GATEWAY_SECRET = original_secret


@pytest.mark.asyncio
async def test_semantic_search_disabled(client, mock_crud):
    with patch("app.views.settings") as mock_settings:
        mock_settings.EMBEDDINGS_ENABLED = False
        mock_settings.MAX_SEARCH_K = 100

        response = await client.get("/api/v1/search/semantic?q=test")
        assert response.status_code == 503
        assert response.json()["detail"] == "Semantic search is temporarily disabled."


@pytest.mark.asyncio
async def test_search_k_limit(client, mock_crud):
    response = await client.get("/api/v1/search/semantic?q=test&k=1000")
    # Should fail validation due to le=settings.MAX_SEARCH_K (100)
    assert response.status_code == 422
