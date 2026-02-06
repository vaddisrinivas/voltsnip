from datetime import datetime
from typing import List, Optional, Literal
from uuid import UUID
from enum import Enum
from pydantic import BaseModel, Field, HttpUrl, ConfigDict, field_validator, constr
from app.constants import (
    SNIPPET_KIND_SNIPPET,
    SNIPPET_KIND_SKILL,
    SNIPPET_KIND_PROMPT,
    SNIPPET_KIND_UTILITY,
    SNIPPET_KIND_CONFIG,
    DESC_TITLE,
    DESC_DESCRIPTION,
    DESC_LANGUAGE,
    DESC_TAGS,
    DESC_KIND,
    DESC_CANONICAL_KEY,
    DESC_CODE,
    DESC_SOURCE,
    DESC_PARENT_ID,
    SETTINGS_EXTRA_FORBID,
    ERR_TOO_MANY_TAGS,
    ERR_TAG_TOO_LONG,
    ERR_CANONICAL_HAS_SPACES,
    ERR_CANONICAL_EMPTY,
    SPACE,
    ACTIVE_STATUS,
    EXPIRED_STATUS,
    SURVIVED_STATUS,
    SNIPPET_SOURCE_DEFAULT,
    FIELD_TAGS,
    FIELD_CANONICAL_KEY,
    VALIDATOR_MODE_BEFORE,
)


class SnippetKind(str, Enum):
    SNIPPET = SNIPPET_KIND_SNIPPET
    SKILL = SNIPPET_KIND_SKILL
    PROMPT = SNIPPET_KIND_PROMPT
    UTILITY = SNIPPET_KIND_UTILITY
    CONFIG = SNIPPET_KIND_CONFIG


class SnippetBase(BaseModel):
    title: Optional[constr(max_length=200)] = Field(
        None, description=DESC_TITLE
    )

    description: Optional[constr(max_length=1000)] = Field(
        None, description=DESC_DESCRIPTION
    )

    language: Optional[constr(max_length=50)] = Field(
        None, description=DESC_LANGUAGE
    )

    tags: List[constr(max_length=50)] = Field(
        default_factory=list,
        description=DESC_TAGS,
    )

    kind: SnippetKind = Field(
        SnippetKind.SNIPPET,
        description=DESC_KIND,
    )

    canonical_key: Optional[constr(max_length=200)] = Field(
        None,
        description=DESC_CANONICAL_KEY,
    )

    model_config = ConfigDict(extra=SETTINGS_EXTRA_FORBID)

    @field_validator(FIELD_TAGS, mode=VALIDATOR_MODE_BEFORE)
    @classmethod
    def validate_tags(cls, tags: List[str]) -> List[str]:
        if len(tags) > 20:
            raise ValueError(ERR_TOO_MANY_TAGS)
        normalized: list[str] = []

        for tag in tags:
            t = tag.strip().lower()
            if not t:
                continue
            if len(t) > 50:
                raise ValueError(ERR_TAG_TOO_LONG % t)
            if t not in normalized:
                normalized.append(t)

        return normalized

    @field_validator(FIELD_CANONICAL_KEY)
    @classmethod
    def validate_canonical_key(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return None

        v_str = v.strip().lower()

        if SPACE in v_str:
            raise ValueError(ERR_CANONICAL_HAS_SPACES)
        if not v_str:
            raise ValueError(ERR_CANONICAL_EMPTY)

        return v_str


class SnippetCreate(SnippetBase):
    code: str = Field(
        ...,
        max_length=1000000,
        description=DESC_CODE,
    ) # 1,000,000 char limit aligns with API enforcement
    source: Optional[str] = Field(
        None, description=DESC_SOURCE
    )
    parent_id: Optional[UUID] = Field(
        None, description=DESC_PARENT_ID
    )


class SnippetUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    tags: Optional[List[str]] = None
    model_config = ConfigDict(extra=SETTINGS_EXTRA_FORBID)


class SnippetMetaResponse(SnippetBase):
    id: UUID
    created_at: datetime
    updated_at: datetime
    expires_at: Optional[datetime] = None
    view_count: int = 0
    upvote_count: int = 0
    downvote_count: int = 0
    reference_count: int = 0
    status: Literal[ACTIVE_STATUS, EXPIRED_STATUS, SURVIVED_STATUS] = ACTIVE_STATUS
    highlighted_url: Optional[HttpUrl] = None
    is_hidden: bool = False
    hidden_reason: Optional[str] = None
    source: str = SNIPPET_SOURCE_DEFAULT

    model_config = ConfigDict(from_attributes=True)


class SnippetDetailResponse(SnippetMetaResponse):
    blob_key: str
    code: str


class Vote(BaseModel):
    value: Literal[-1, 1]
    model_config = ConfigDict(extra=SETTINGS_EXTRA_FORBID)


class AgentIngestRequest(BaseModel):
    agent_name: str
    skills_version: str
    snippets: List[SnippetCreate]

    model_config = ConfigDict(extra=SETTINGS_EXTRA_FORBID)
