from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.constants import EMPTY_STRING
from app.services import EmbeddingsService, LocalStorage, StorageService


@pytest.mark.asyncio
async def test_local_storage_round_trip(tmp_path, fake):
    storage = LocalStorage(str(tmp_path))
    key = "snippets/demo.txt"
    content = fake.text(max_nb_chars=120)

    await storage.write_text(key, content)
    assert (tmp_path / key).exists()
    assert await storage.read_text(key) == content


@pytest.mark.parametrize("prefix", ["file://", ""])
def test_storage_service_normalizes_file_uri(prefix, tmp_path):
    uri = f"{prefix}{tmp_path}"
    settings = SimpleNamespace(
        STORAGE_PROVIDER="local",
        STORAGE_URI=uri,
        STORAGE_BUCKET_NAME="unused",
        AWS_ACCESS_KEY_ID=None,
        AWS_SECRET_ACCESS_KEY=None,
        AWS_REGION=None,
        STORAGE_ENDPOINT=None,
        AZURE_STORAGE_CONNECTION_STRING=None,
    )

    with patch("app.services.settings", settings):
        service = StorageService()

    assert service.root_path == str(tmp_path)


@pytest.mark.asyncio
@pytest.mark.parametrize("exc", [RuntimeError("boom"), OSError("nope")])
async def test_storage_service_upload_handles_exception(exc, tmp_path):
    settings = SimpleNamespace(
        STORAGE_PROVIDER="local",
        STORAGE_URI=str(tmp_path),
        STORAGE_BUCKET_NAME="unused",
        AWS_ACCESS_KEY_ID=None,
        AWS_SECRET_ACCESS_KEY=None,
        AWS_REGION=None,
        STORAGE_ENDPOINT=None,
        AZURE_STORAGE_CONNECTION_STRING=None,
    )

    with patch("app.services.settings", settings):
        service = StorageService()
        service.storage = MagicMock()
        service.storage.write_text = AsyncMock(side_effect=exc)
        ok = await service.upload_snippet("key", "data")

    assert ok is False


@pytest.mark.asyncio
async def test_storage_service_get_snippet_content_returns_empty(tmp_path):
    settings = SimpleNamespace(
        STORAGE_PROVIDER="local",
        STORAGE_URI=str(tmp_path),
        STORAGE_BUCKET_NAME="unused",
        AWS_ACCESS_KEY_ID=None,
        AWS_SECRET_ACCESS_KEY=None,
        AWS_REGION=None,
        STORAGE_ENDPOINT=None,
        AZURE_STORAGE_CONNECTION_STRING=None,
    )

    with patch("app.services.settings", settings):
        service = StorageService()
        service.storage = MagicMock()
        service.storage.read_text = AsyncMock(side_effect=RuntimeError("boom"))
        content = await service.get_snippet_content("key")

    assert content == EMPTY_STRING


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "enabled, expected",
    [
        (False, []),
        (True, [0.1, 0.2]),
    ],
)
async def test_embeddings_service_generate_embedding_with_patch(enabled, expected):
    settings = SimpleNamespace(EMBEDDINGS_ENABLED=enabled)

    class FakeVector:
        def __init__(self, values):
            self._values = values

        def tolist(self):
            return list(self._values)

    class FakeModel:
        def embed(self, texts):
            return [FakeVector([0.1, 0.2])]

    with patch("app.services.settings", settings):
        service = EmbeddingsService()
        if enabled:
            service.model = FakeModel()
            with patch.object(service, "_load_model") as load:
                result = await service.generate_embedding("hello")
                load.assert_called_once()
        else:
            with patch.object(service, "_load_model") as load:
                result = await service.generate_embedding("hello")
                load.assert_not_called()

    assert result == expected
