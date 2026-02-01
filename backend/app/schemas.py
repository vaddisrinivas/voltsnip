from datetime import datetime
from typing import List, Optional, Literal
from uuid import UUID
from enum import Enum
from pydantic import BaseModel, Field, HttpUrl, ConfigDict, field_validator, constr


# 1) Kinds supported in your backend
class SnippetKind(str, Enum):
    SNIPPET = "snippet"
    SKILL = "skill"
    PROMPT = "prompt"
    UTILITY = "utility"
    CONFIG = "config"


class SnippetBase(BaseModel):
    """
    Base schema for snippets and skills, used for creation & ingestion endpoints.
    """

    title: Optional[constr(max_length=200)] = Field(
        None, description="Human-friendly title for the snippet"
    )

    description: Optional[constr(max_length=1000)] = Field(
        None, description="Context or explanation for the snippet"
    )

    language: Optional[constr(max_length=50)] = Field(
        None, description="Programming language or format of the snippet"
    )

    tags: List[constr(max_length=50)] = Field(
        default_factory=list,
        description="List of normalized tags associated with this snippet",
    )

    kind: SnippetKind = Field(
        SnippetKind.SNIPPET,
        description="The type of snippet (e.g., snippet, skill, prompt, utility, config)",
    )

    canonical_key: Optional[constr(max_length=200)] = Field(
        None,
        description="Stable string used to identify the same intent over time (e.g., slug)",
    )

    model_config = ConfigDict(extra="forbid")

    @field_validator("tags", mode="before")
    @classmethod
    def validate_tags(cls, tags: List[str]) -> List[str]:
        """
        Normalize tags: lowercase, strip, remove duplicates, max count.
        """
        if len(tags) > 20:
            raise ValueError("Too many tags (max 20)")
        normalized: list[str] = []

        for tag in tags:
            t = tag.strip().lower()
            if not t:
                continue
            if len(t) > 50:
                raise ValueError(f"Tag too long: {t} (max 50 characters)")
            if t not in normalized:
                normalized.append(t)

        return normalized

    @field_validator("canonical_key")
    @classmethod
    def validate_canonical_key(cls, v: Optional[str]) -> Optional[str]:
        """
        Enforce lowercase & simple slug chars if provided.
        """
        if v is None:
            return None

        v_str = v.strip().lower()

        if " " in v_str:
            raise ValueError("canonical_key cannot contain spaces")
        if not v_str:
            raise ValueError("canonical_key cannot be empty")

        # You can expand this pattern if you need deeper slug rules
        return v_str


class SnippetCreate(SnippetBase):
    code: str = Field(
        ..., max_length=100000, description="The actual code or text content"
    )


class SnippetUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    tags: Optional[List[str]] = None
    model_config = ConfigDict(extra="forbid")


class SnippetMetaResponse(SnippetBase):
    id: UUID
    created_at: datetime
    updated_at: datetime
    expires_at: Optional[datetime] = None
    view_count: int = 0
    upvote_count: int = 0
    downvote_count: int = 0
    reference_count: int = 0
    status: Literal["active", "expired", "survived"] = "active"
    highlighted_url: Optional[HttpUrl] = None
    is_hidden: bool = False
    hidden_reason: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)


class SnippetDetailResponse(SnippetMetaResponse):
    blob_key: str
    code: str


class Vote(BaseModel):
    value: Literal[-1, 1]
    model_config = ConfigDict(extra="forbid")


class AgentIngestRequest(BaseModel):
    agent_name: str
    skills_version: str
    snippets: List[SnippetCreate]

    model_config = ConfigDict(extra="forbid")
