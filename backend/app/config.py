from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import Optional, Literal
from pydantic import field_validator
import json


class Settings(BaseSettings):
    DATABASE_URL: str
    STORAGE_BUCKET_NAME: str = "local-bucket"
    AWS_ACCESS_KEY_ID: Optional[str] = None
    AWS_SECRET_ACCESS_KEY: Optional[str] = None
    AWS_REGION: str = "us-east-1"
    AZURE_STORAGE_CONNECTION_STRING: Optional[str] = None
    VOLTSNIP_GATEWAY_SECRET: Optional[str] = None
    STORAGE_PROVIDER: Literal["s3", "azure", "local"] = "local"
    STORAGE_PUBLIC_READ: bool = True
    STORAGE_URI: Optional[str] = None
    STORAGE_ENDPOINT: Optional[str] = None
    EMBEDDINGS_ENABLED: bool = True
    TRENDING_WINDOW_HOURS: int = 24
    MAX_CODE_SIZE: int = 1048576
    MAX_TAGS: int = 20
    MAX_SEARCH_K: int = 100
    EXPIRATION_HOURS: int = 24
    TOP_FEED_WINDOW_HOURS: int = 24
    CORS_ORIGINS: list[str] | str = ["*"]

    @field_validator("CORS_ORIGINS", mode="before")
    @classmethod
    def parse_cors_origins(cls, v):
        if isinstance(v, str):
            v_stripped = v.strip()
            if v_stripped.startswith("[") and v_stripped.endswith("]"):
                try:
                    return json.loads(v_stripped)
                except Exception:
                    pass
            return [x.strip() for x in v_stripped.split(",") if x.strip()]
        return v

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    @property
    def MIGRATION_DATABASE_URL(self) -> str:
        return self.DATABASE_URL.replace("postgresql+asyncpg", "postgresql+psycopg")

settings = Settings()
