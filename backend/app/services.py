import os
import logging
import asyncio
from typing import List
from starlette.concurrency import run_in_threadpool
from app.config import settings

try:
    import boto3
except ImportError:
    boto3 = None

try:
    from azure.storage.blob import BlobServiceClient
except ImportError:
    BlobServiceClient = None

logger = logging.getLogger(__name__)


class StorageService:
    def __init__(self):
        self.provider = settings.STORAGE_PROVIDER.lower()
        
        if self.provider == "local":
            if settings.AZURE_STORAGE_CONNECTION_STRING or os.getenv("AZURE_STORAGE_CONNECTION_STRING"):
                self.provider = "azure"
            elif settings.AWS_ACCESS_KEY_ID and settings.AWS_SECRET_ACCESS_KEY:
                self.provider = "s3"
             
        self.bucket = getattr(settings, "STORAGE_BUCKET_NAME", "voltsnip-bucket")
        self.s3_client = None
        self.azure_client = None
        self.root_path = "local_storage"

        if self.provider == "s3":
            if boto3:
                self.s3_client = boto3.client(
                    "s3",
                    aws_access_key_id=settings.AWS_ACCESS_KEY_ID,
                    aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY,
                    region_name=getattr(settings, "AWS_REGION", "us-east-1"),
                    endpoint_url=getattr(settings, "STORAGE_ENDPOINT", None)
                )
            else:
                logger.error("boto3 not installed for AWS provider.")
                
        elif self.provider == "azure":
            conn_str = settings.AZURE_STORAGE_CONNECTION_STRING
            if not conn_str:
                conn_str = os.getenv("AZURE_STORAGE_CONNECTION_STRING")
            
            if not conn_str:
                logger.warning("AZURE_STORAGE_CONNECTION_STRING not set for Azure provider.")
            elif BlobServiceClient:
                self.azure_client = BlobServiceClient.from_connection_string(conn_str)
            else:
                logger.error("azure-storage-blob not installed for Azure provider.")
                
        else:
            self.provider = "local"
            uri = getattr(settings, "STORAGE_URI", "local_storage")
            if uri and "://" in uri:
                 if uri.startswith("file://"):
                     self.root_path = uri.replace("file://", "")
            else:
                self.root_path = uri or "local_storage"
            os.makedirs(self.root_path, exist_ok=True)

    async def upload_snippet(self, key: str, content: str) -> bool:
        loop = asyncio.get_event_loop()
        
        if self.provider == "local":
            try:
                path = os.path.join(self.root_path, key)
                os.makedirs(os.path.dirname(path), exist_ok=True)
                with open(path, "w") as f:
                    f.write(content)
                return True
            except Exception as e:
                logger.error(f"Local Upload Error: {e}")
                return False

        elif self.provider == "s3":
            public = getattr(settings, "STORAGE_PUBLIC_READ", True)
            extra_args = {'ACL': 'public-read'} if public else {}
            
            def _s3_up():
                self.s3_client.put_object(Bucket=self.bucket, Key=key, Body=content, **extra_args)
                
            try:
                await loop.run_in_executor(None, _s3_up)
                return True
            except Exception as e:
                logger.error(f"AWS Upload Error: {e}")
                return False

        elif self.provider == "azure":
             if not self.azure_client:
                 return False
             
             def _az_up():
                 container = self.azure_client.get_container_client(self.bucket)
                 if not container.exists():
                     container.create_container()
                 blob = container.get_blob_client(key)
                 blob.upload_blob(content, overwrite=True)
                 
                 try:
                     props = blob.get_blob_properties()
                     print(f"\n[Azure Metadata] Uploaded: {key}")
                     print(f"  - Size: {props.size} bytes")
                     print(f"  - Content Type: {props.content_settings.content_type}")
                     print(f"  - Last Modified: {props.last_modified}")
                     print(f"  - ETag: {props.etag}")
                     print(f"  - Blob Type: {props.blob_type}\n")
                 except Exception as e:
                     print(f"[Azure Metadata] Failed to fetch properties: {e}")
                 
             try:
                 await loop.run_in_executor(None, _az_up)
                 return True
             except Exception as e:
                 logger.error(f"Azure Upload Error: {e}")
                 return False
                 
        return False

    async def get_snippet_content(self, key: str) -> str:
        loop = asyncio.get_event_loop()
        
        if self.provider == "local":
            try:
                path = os.path.join(self.root_path, key)
                with open(path, "r") as f:
                    return f.read()
            except Exception:
                return ""

        elif self.provider == "s3":
            def _s3_get():
                obj = self.s3_client.get_object(Bucket=self.bucket, Key=key)
                return obj["Body"].read().decode("utf-8")
            try:
                 return await run_in_threadpool(_s3_get)
            except Exception:
                 return ""

        elif self.provider == "azure":
             if not self.azure_client:
                 return ""
             def _az_get():
                 container = self.azure_client.get_container_client(self.bucket)
                 blob = container.get_blob_client(key)
                 return blob.download_blob().readall().decode("utf-8")
             try:
                 return await loop.run_in_executor(None, _az_get)
             except Exception:
                 return ""
                 
        return ""

    async def list_files(self, prefix: str) -> List[str]:
        if self.provider == "local":
             results = []
             base = os.path.join(self.root_path, prefix)
             if os.path.exists(base):
                 for root, dirs, files in os.walk(base):
                     for f in files:
                         results.append(os.path.join(root, f))
             return results
        return []


class EmbeddingsService:
    def __init__(self, model_name: str = "BAAI/bge-small-en-v1.5"):
        self.model_name = model_name
        self.model = None

    def _load_model(self):
        if not self.model:
            logger.info(f"Loading embedding model: {self.model_name}")
            try:
                from fastembed import TextEmbedding
                self.model = TextEmbedding(model_name=self.model_name)
            except ValueError:
                logger.warning(
                    f"FastEmbed model {self.model_name} not found, falling back to default."
                )
                self.model = TextEmbedding(model_name="BAAI/bge-small-en-v1.5")

    async def generate_embedding(self, text: str) -> List[float]:
        if not settings.EMBEDDINGS_ENABLED:
            logger.warning("Embedding generation requested but service is disabled.")
            return []

        def _generate():
            self._load_model()
            if hasattr(self.model, "embed"):
                return list(self.model.embed([text]))[0].tolist()
            return []

        try:
            return await run_in_threadpool(_generate)
        except Exception as e:
            logger.error(f"Embedding generation failed: {e}")
            raise e
