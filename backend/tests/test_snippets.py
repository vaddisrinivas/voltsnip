import pytest
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
def mock_crud():
    with patch("app.views.crud") as mock_crud:
        unified_mock = MagicMock()
        unified_mock.create_snippet = AsyncMock()
        unified_mock.get_snippet = AsyncMock()
        unified_mock.increment_view = AsyncMock()
        unified_mock.vote_snippet = AsyncMock()

        unified_mock.get_trending_feed = AsyncMock()
        unified_mock.get_hot_feed = AsyncMock()
        unified_mock.get_top_feed = AsyncMock()
        unified_mock.get_most_used_feed = AsyncMock()

        unified_mock.search_snippets = AsyncMock()
        unified_mock.get_snippet_by_hash = AsyncMock(return_value=None)

        mock_crud.create_snippet = unified_mock.create_snippet
        mock_crud.get_snippet = unified_mock.get_snippet
        mock_crud.increment_view = unified_mock.increment_view
        mock_crud.vote_snippet = unified_mock.vote_snippet

        mock_crud.get_trending_feed = unified_mock.get_trending_feed
        mock_crud.get_hot_feed = unified_mock.get_hot_feed
        mock_crud.get_top_feed = unified_mock.get_top_feed
        mock_crud.get_most_used_feed = unified_mock.get_most_used_feed

        mock_crud.search_snippets = unified_mock.search_snippets
        mock_crud.semantic_search_snippets = AsyncMock()
        mock_crud.get_snippet_by_hash = unified_mock.get_snippet_by_hash

        yield mock_crud


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
    # Testing MAX_CODE_SIZE (100KB default)
    large_code = "A" * 100001
    response = await client.post(
        "/api/v1/snippets/",
        json={"title": "Large Snippet", "code": large_code, "language": "python"},
    )
    # This should be caught by our manual check in views.py or Pydantic max_length
    assert response.status_code in [413, 422]


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
