from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import Optional, Literal


class Settings(BaseSettings):
    DATABASE_URL: str
    STORAGE_BUCKET_NAME: str = "local-bucket"
    AWS_ACCESS_KEY_ID: Optional[str] = None
    AWS_SECRET_ACCESS_KEY: Optional[str] = None
    AWS_REGION: str = "us-east-1"
    AZURE_STORAGE_CONNECTION_STRING: Optional[str] = None

    # Storage Provider: s3, azure, local
    STORAGE_PROVIDER: Literal["s3", "azure", "local"] = "local"
    STORAGE_PUBLIC_READ: bool = True
    
    # Generic Storage (fsspec)
    # Examples: s3://bucket, az://container, gcs://bucket, local://path, or just a path
    STORAGE_URI: Optional[str] = None
    STORAGE_ENDPOINT: Optional[str] = None

    # Cost & Safety Guards
    EMBEDDINGS_ENABLED: bool = True
    TRENDING_WINDOW_DAYS: int = 7
    MAX_CODE_SIZE: int = 100_000
    MAX_TAGS: int = 20
    MAX_SEARCH_K: int = 100

    # Secure CORS settings
    CORS_ORIGINS: list[str] | str = ["*"]

    from pydantic import field_validator

    @field_validator("CORS_ORIGINS", mode="before")
    @classmethod
    def parse_cors_origins(cls, v):
        if isinstance(v, str):
            v_stripped = v.strip()
            if v_stripped.startswith("[") and v_stripped.endswith("]"):
                import json

                try:
                    return json.loads(v_stripped)
                except Exception:
                    pass
            # Handle CSV or a single item (like "*")
            return [x.strip() for x in v_stripped.split(",") if x.strip()]
        return v

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    @property
    def MIGRATION_DATABASE_URL(self) -> str:
        """
        Returns a sync database URL for Alembic.
        Replaces postgresql+asyncpg with postgresql+psycopg
        """
        return self.DATABASE_URL.replace("postgresql+asyncpg", "postgresql+psycopg")


settings = Settings()
