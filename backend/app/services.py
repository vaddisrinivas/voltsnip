import os
import asyncio
from typing import List, Mapping, Any, Optional
import aiofiles
import aiofiles.os

from app.globals import logger, settings
from app.constants import (
    STORAGE_PROVIDER_S3,
    STORAGE_PROVIDER_AZURE,
    DEFAULT_STORAGE_ROOT,
    FILE_URI_PREFIX,
    FILE_MODE_WRITE,
    FILE_MODE_READ,
    ENCODING_UTF8,
    AZURE_STORAGE_IMPORT_ERROR,
    AZURE_STORAGE_INIT_FAILED_LOG,
    S3_STORAGE_IMPORT_ERROR,
    S3_STORAGE_INIT_FAILED_LOG,
    UPLOAD_ERROR_LOG,
    EMBEDDINGS_MODEL_DEFAULT,
    EMBEDDING_MODEL_LOADING_LOG,
    EMBEDDING_MODEL_NOT_FOUND_LOG,
    EMBEDDINGS_DISABLED_LOG,
    EMBEDDING_GENERATION_FAILED_LOG,
    EMBEDDINGS_MODEL_ATTR,
    EMPTY_STRING,
)


class BaseAsyncStorage:
    async def write_text(self, key: str, content: str) -> None:
        raise NotImplementedError

    async def read_text(self, key: str) -> str:
        raise NotImplementedError

    async def list_files(self, prefix: str) -> List[str]:
        return []


class LocalStorage(BaseAsyncStorage):
    def __init__(self, root_path: str):
        self.root_path = root_path
        os.makedirs(self.root_path, exist_ok=True)

    def _resolve_path(self, key: str) -> str:
        return os.path.join(self.root_path, key)

    async def write_text(self, key: str, content: str) -> None:
        path = self._resolve_path(key)
        await aiofiles.os.makedirs(os.path.dirname(path), exist_ok=True)
        async with aiofiles.open(path, FILE_MODE_WRITE) as f:
            await f.write(content)

    async def read_text(self, key: str) -> str:
        path = self._resolve_path(key)
        async with aiofiles.open(path, FILE_MODE_READ) as f:
            return await f.read()

    async def list_files(self, prefix: str) -> List[str]:
        return []


class AzureStorage(BaseAsyncStorage):
    def __init__(self, connection_string: str, container_name: str):
        self.connection_string = connection_string
        self.container_name = container_name
        self._container_client = None
        self._container_ready = False
        self._lock = asyncio.Lock()

    async def _get_container(self):
        if self._container_client is not None:
            return self._container_client
        try:
            from azure.storage.blob.aio import BlobServiceClient
        except ImportError:
            logger.error(AZURE_STORAGE_IMPORT_ERROR)
            raise
        try:
            service_client = BlobServiceClient.from_connection_string(self.connection_string)
            self._container_client = service_client.get_container_client(self.container_name)
            return self._container_client
        except Exception as e:
            logger.error(AZURE_STORAGE_INIT_FAILED_LOG, e)
            raise

    async def _ensure_container(self):
        if self._container_ready:
            return
        async with self._lock:
            if self._container_ready:
                return
            container = await self._get_container()
            exists = await container.exists()
            if not exists:
                await container.create_container()
            self._container_ready = True

    async def write_text(self, key: str, content: str) -> None:
        await self._ensure_container()
        container = await self._get_container()
        await container.upload_blob(key, content.encode(ENCODING_UTF8), overwrite=True)

    async def read_text(self, key: str) -> str:
        await self._ensure_container()
        container = await self._get_container()
        stream = await container.download_blob(key)
        data = await stream.readall()
        return data.decode(ENCODING_UTF8)


class S3Storage(BaseAsyncStorage):
    def __init__(
        self,
        bucket_name: str,
        aws_access_key_id: Optional[str],
        aws_secret_access_key: Optional[str],
        region_name: Optional[str],
        endpoint_url: Optional[str],
    ):
        try:
            import aioboto3
        except ImportError:
            logger.error(S3_STORAGE_IMPORT_ERROR)
            raise
        self.session = aioboto3.Session(
            aws_access_key_id=aws_access_key_id,
            aws_secret_access_key=aws_secret_access_key,
            region_name=region_name,
        )
        self.bucket_name = bucket_name
        self.endpoint_url = endpoint_url

    def _client(self):
        return self.session.client("s3", endpoint_url=self.endpoint_url)

    async def write_text(self, key: str, content: str) -> None:
        try:
            async with self._client() as s3:
                await s3.put_object(
                    Bucket=self.bucket_name,
                    Key=key,
                    Body=content.encode(ENCODING_UTF8),
                )
        except Exception as e:
            logger.error(S3_STORAGE_INIT_FAILED_LOG, e)
            raise

    async def read_text(self, key: str) -> str:
        try:
            async with self._client() as s3:
                response = await s3.get_object(Bucket=self.bucket_name, Key=key)
                data = await response["Body"].read()
                return data.decode(ENCODING_UTF8)
        except Exception as e:
            logger.error(S3_STORAGE_INIT_FAILED_LOG, e)
            raise


class StorageService:
    def __init__(self):
        self.provider = settings.STORAGE_PROVIDER.lower()
        self.storage = None
        self.root_path = None

        if self.provider == STORAGE_PROVIDER_S3:
            self.storage = S3Storage(
                aws_access_key_id=settings.AWS_ACCESS_KEY_ID,
                aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY,
                region_name=settings.AWS_REGION,
                bucket_name=settings.STORAGE_BUCKET_NAME,
                endpoint_url=settings.STORAGE_ENDPOINT,
            )
        elif self.provider == STORAGE_PROVIDER_AZURE:
            self.storage = AzureStorage(
                connection_string=settings.AZURE_STORAGE_CONNECTION_STRING,
                container_name=settings.STORAGE_BUCKET_NAME,
            )
        else:
            root_path = settings.STORAGE_URI or DEFAULT_STORAGE_ROOT
            root_path = self._normalize_root_path(root_path)
            self.root_path = root_path
            self.storage = LocalStorage(root_path)

    def _normalize_root_path(self, root_path: str) -> str:
        if root_path.startswith(FILE_URI_PREFIX):
            return root_path.replace(FILE_URI_PREFIX, EMPTY_STRING)
        return root_path

    async def upload_snippet(
        self,
        key: str,
        content: str,
        metadata: Mapping[str, Any] | None = None,
    ) -> bool:
        try:
            await self.storage.write_text(key, content)
            return True
        except Exception as e:
            logger.error(UPLOAD_ERROR_LOG, e)
            return False

    async def get_snippet_content(self, key: str) -> str:
        try:
            return await self.storage.read_text(key)
        except Exception:
            return EMPTY_STRING

    async def list_files(self, prefix: str) -> List[str]:
        return await self.storage.list_files(prefix)



class EmbeddingsService:
    def __init__(self, model_name: str = EMBEDDINGS_MODEL_DEFAULT):
        self.model_name = model_name
        self.model = None

    def _load_model(self):
        if not self.model:
            logger.info(EMBEDDING_MODEL_LOADING_LOG, self.model_name)
            try:
                from fastembed import TextEmbedding
                self.model = TextEmbedding(model_name=self.model_name)
            except ValueError:
                logger.warning(EMBEDDING_MODEL_NOT_FOUND_LOG, self.model_name)
                self.model = TextEmbedding(model_name=EMBEDDINGS_MODEL_DEFAULT)

    async def generate_embedding(self, text: str) -> List[float]:
        if not settings.EMBEDDINGS_ENABLED:
            logger.warning(EMBEDDINGS_DISABLED_LOG)
            return []

        def _generate():
            self._load_model()
            if hasattr(self.model, EMBEDDINGS_MODEL_ATTR):
                return list(self.model.embed([text]))[0].tolist()
            return []

        try:
            return await asyncio.to_thread(_generate)
        except Exception as e:
            logger.error(EMBEDDING_GENERATION_FAILED_LOG, e)
            raise e
