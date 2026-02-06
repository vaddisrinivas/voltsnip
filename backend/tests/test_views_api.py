import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from app import views
from app.constants import ERR_SNIPPET_NOT_FOUND, ERR_UPLOAD_FAILED
from app.schemas import SnippetDetailResponse


@pytest.fixture
def mock_crud(monkeypatch):
    mock = MagicMock()
    mock.get_snippet = AsyncMock(return_value=None)
    mock.get_snippet_by_hash = AsyncMock(return_value=None)
    mock.create_snippet = AsyncMock()
    mock.create_snippet_reference = AsyncMock()
    monkeypatch.setattr(views, "crud", mock)
    return mock


@pytest.mark.asyncio
async def test_create_snippet_parent_missing(client, mock_crud):
    parent_id = uuid.uuid4()
    response = await client.post(
        "/api/v1/snippets/",
        json={
            "title": "Parent missing",
            "code": "print('hello')",
            "language": "python",
            "tags": ["python"],
            "parent_id": str(parent_id),
        },
    )
    assert response.status_code == 404
    assert response.json()["detail"] == ERR_SNIPPET_NOT_FOUND


@pytest.mark.asyncio
async def test_create_snippet_creates_reference(client, mock_crud, mock_snippet):
    parent_id = uuid.uuid4()
    mock_crud.get_snippet.return_value = mock_snippet
    mock_snippet.code = "print('child')"
    mock_crud.create_snippet.return_value = mock_snippet

    response = await client.post(
        "/api/v1/snippets/",
        json={
            "title": "Child snippet",
            "code": "print('child')",
            "language": "python",
            "tags": ["python"],
            "parent_id": str(parent_id),
        },
    )

    assert response.status_code == 200
    mock_crud.create_snippet_reference.assert_awaited_once()
    args = mock_crud.create_snippet_reference.await_args.args
    assert args[1] == parent_id
    assert args[2] == mock_snippet.id


@pytest.mark.asyncio
async def test_create_snippet_duplicate_hash_returns_existing(
    client, mock_crud, mock_snippet
):
    mock_snippet.blob_key = "snippets/existing.py"
    mock_crud.get_snippet_by_hash.return_value = mock_snippet

    response = await client.post(
        "/api/v1/snippets/",
        json={
            "title": "Dup",
            "code": "print('dup')",
            "language": "python",
            "tags": ["python"],
        },
    )

    assert response.status_code == 200
    assert response.json()["code"] == "mocked code content"
    assert mock_crud.create_snippet.await_count == 0


@pytest.mark.asyncio
async def test_create_snippet_upload_failed(client, mock_crud, mock_snippet, monkeypatch):
    mock_snippet.code = "print('fail')"
    mock_crud.create_snippet.return_value = mock_snippet
    views.storage_service.upload_snippet = AsyncMock(return_value=False)

    response = await client.post(
        "/api/v1/snippets/",
        json={
            "title": "Fail upload",
            "code": "print('fail')",
            "language": "python",
            "tags": ["python"],
        },
    )

    assert response.status_code == 500
    assert response.json()["detail"] == ERR_UPLOAD_FAILED


@pytest.mark.asyncio
async def test_read_snippet_etag_from_cache(client, monkeypatch):
    snippet_id = uuid.uuid4()
    updated_at = datetime(2025, 1, 1, tzinfo=timezone.utc)
    payload = SnippetDetailResponse(
        id=snippet_id,
        title="Cached",
        description=None,
        language="python",
        tags=["python"],
        kind="snippet",
        canonical_key=None,
        blob_key="snippets/cached.py",
        code="print('cached')",
        created_at=updated_at,
        updated_at=updated_at,
        expires_at=None,
        view_count=1,
        upvote_count=1,
        downvote_count=0,
        reference_count=0,
        status="active",
        highlighted_url=None,
        is_hidden=False,
        hidden_reason=None,
        source="human",
    ).model_dump()
    monkeypatch.setattr(views, "get_cached_snippet", AsyncMock(return_value=payload))

    etag = views._compute_snippet_etag(snippet_id, updated_at)
    response = await client.get(
        f"/api/v1/snippets/{snippet_id}",
        headers={"if-none-match": etag},
    )

    assert response.status_code == 304
