from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import Optional, Literal
from pydantic import field_validator
from pathlib import Path
import json
from app.constants import (
    DEFAULT_STORAGE_BUCKET_NAME,
    DEFAULT_AWS_REGION,
    STORAGE_PROVIDER_S3,
    STORAGE_PROVIDER_AZURE,
    STORAGE_PROVIDER_LOCAL,
    DEFAULT_STORAGE_PROVIDER,
    DEFAULT_CORS_ORIGINS,
    SETTINGS_CORS_ORIGINS_FIELD,
    VALIDATOR_MODE_BEFORE,
    LEFT_BRACKET,
    RIGHT_BRACKET,
    COMMA,
    ENV_FILE_NAME,
    SETTINGS_EXTRA_IGNORE,
    MIGRATION_DB_ASYNC_PREFIX,
    MIGRATION_DB_SYNC_PREFIX,
    DEFAULT_FEED_CACHE_TTL_SECONDS,
    DEFAULT_SNIPPET_CACHE_TTL_SECONDS,
    DEFAULT_SNIPPET_CACHE_MAX_AGE_SECONDS,
    DEFAULT_APP_VERSION,
)

def _read_version_from_pyproject(path: Path) -> Optional[str]:
    if not path.exists():
        return None
    text = path.read_text(encoding="utf-8")
    in_project = False
    for line in text.splitlines():
        stripped = line.strip()
        if stripped == "[project]":
            in_project = True
            continue
        if in_project and stripped.startswith("["):
            break
        if in_project and stripped.startswith("version"):
            _, _, value = stripped.partition("=")
            return value.strip().strip('"')
    return None


def _resolve_version() -> str:
    here = Path(__file__).resolve()
    candidates = [
        here.parents[2] / "VERSION",  # repo root when available
        here.parents[1] / "VERSION",  # backend/VERSION if present
    ]
    for path in candidates:
        if path.exists():
            return path.read_text(encoding="utf-8").strip()
    pyproject_version = _read_version_from_pyproject(here.parents[1] / "pyproject.toml")
    if pyproject_version:
        return pyproject_version
    return DEFAULT_APP_VERSION


class Settings(BaseSettings):
    DATABASE_URL: str
    VERSION: str = _resolve_version()
    STORAGE_BUCKET_NAME: str = DEFAULT_STORAGE_BUCKET_NAME
    AWS_ACCESS_KEY_ID: Optional[str] = None
    AWS_SECRET_ACCESS_KEY: Optional[str] = None
    AWS_REGION: str = DEFAULT_AWS_REGION
    AZURE_STORAGE_CONNECTION_STRING: Optional[str] = None
    VOLTSNIP_GATEWAY_SECRET: Optional[str] = None
    STORAGE_PROVIDER: Literal[
        STORAGE_PROVIDER_S3,
        STORAGE_PROVIDER_AZURE,
        STORAGE_PROVIDER_LOCAL,
    ] = DEFAULT_STORAGE_PROVIDER
    STORAGE_PUBLIC_READ: bool = True
    STORAGE_URI: Optional[str] = None
    STORAGE_ENDPOINT: Optional[str] = None
    EMBEDDINGS_ENABLED: bool = True
    STATS_ENABLED: bool = True
    TRENDING_WINDOW_HOURS: int = 24
    MAX_CODE_SIZE: int = 1000000
    MAX_TAGS: int = 20
    MAX_SEARCH_K: int = 100
    EXPIRATION_HOURS: int = 24
    TOP_FEED_WINDOW_HOURS: int = 24
    FEED_CACHE_TTL_SECONDS: int = DEFAULT_FEED_CACHE_TTL_SECONDS
    SNIPPET_CACHE_TTL_SECONDS: int = DEFAULT_SNIPPET_CACHE_TTL_SECONDS
    SNIPPET_CACHE_MAX_AGE_SECONDS: int = DEFAULT_SNIPPET_CACHE_MAX_AGE_SECONDS
    CORS_ORIGINS: list[str] | str = DEFAULT_CORS_ORIGINS
    MCP_SAMPLING_ENABLED: bool = True
    MCP_SAMPLING_PROVIDER: Literal["auto", "openai", "anthropic", "none"] = "auto"
    MCP_SAMPLING_HANDLER_BEHAVIOR: Literal["fallback", "always"] = "fallback"
    MCP_SAMPLING_OPENAI_MODEL: str = "gpt-5-mini"
    MCP_SAMPLING_ANTHROPIC_MODEL: str = "claude-sonnet-4-5"

    @field_validator(SETTINGS_CORS_ORIGINS_FIELD, mode=VALIDATOR_MODE_BEFORE)
    @classmethod
    def parse_cors_origins(cls, v):
        if isinstance(v, str):
            v_stripped = v.strip()
            if v_stripped.startswith(LEFT_BRACKET) and v_stripped.endswith(RIGHT_BRACKET):
                try:
                    return json.loads(v_stripped)
                except Exception:
                    pass
            return [x.strip() for x in v_stripped.split(COMMA) if x.strip()]
        return v

    model_config = SettingsConfigDict(
        env_file=ENV_FILE_NAME,
        extra=SETTINGS_EXTRA_IGNORE,
    )

    @property
    def MIGRATION_DATABASE_URL(self) -> str:
        return self.DATABASE_URL.replace(
            MIGRATION_DB_ASYNC_PREFIX,
            MIGRATION_DB_SYNC_PREFIX,
        )
