from sqlalchemy import String, Integer, Text, Index, func, text, Boolean, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.dialects.postgresql import UUID, ARRAY, TIMESTAMP
from pgvector.sqlalchemy import Vector
from datetime import datetime
import uuid
from app.database import Base
from app.constants import (
    TABLE_SNIPPETS,
    TABLE_SNIPPET_EMBEDDINGS,
    TABLE_STATS,
    TABLE_SNIPPET_REFERENCES,
    FK_SNIPPETS_ID,
    ACTIVE_STATUS,
    SNIPPET_KIND_SNIPPET,
    SNIPPET_SOURCE_DEFAULT,
    SERVER_DEFAULT_ZERO,
    SERVER_DEFAULT_ONE,
    SERVER_DEFAULT_FALSE,
    EMPTY_PG_ARRAY_TEXT,
    POSTGRES_USING_GIN,
    POSTGRES_USING_HNSW,
    POSTGRES_VECTOR_OPS_KEY,
    POSTGRES_VECTOR_OPS_VALUE,
    IDX_SNIPPETS_EXPIRES_AT,
    IDX_SNIPPETS_CREATED_AT,
    IDX_SNIPPETS_UPVOTES,
    IDX_SNIPPETS_TAGS,
    IDX_SNIPPETS_STATUS,
    IDX_SNIPPETS_SOURCE_HASH,
    IDX_SNIPPETS_VISIBILITY,
    IDX_SNIPPETS_LANGUAGE,
    IDX_SNIPPETS_KIND,
    IDX_SNIPPETS_CANONICAL,
    IDX_SNIPPET_EMBEDDINGS_SNIPPET_ID,
    IDX_SNIPPET_EMBEDDINGS_VECTOR,
    IDX_SNIPPET_REFERENCES_PARENT,
    IDX_SNIPPET_REFERENCES_CHILD,
    FK_ONDELETE_CASCADE,
)


class Snippet(Base):
    __tablename__ = TABLE_SNIPPETS

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    title: Mapped[str] = mapped_column(Text, nullable=True)
    description: Mapped[str] = mapped_column(Text, nullable=True)
    language: Mapped[str] = mapped_column(String(50), nullable=True)
    kind: Mapped[str] = mapped_column(
        String(50), nullable=False, server_default=SNIPPET_KIND_SNIPPET, default=SNIPPET_KIND_SNIPPET
    )

    tags: Mapped[list[str]] = mapped_column(
        ARRAY(String), nullable=False, server_default=text(EMPTY_PG_ARRAY_TEXT)
    )

    blob_key: Mapped[str] = mapped_column(Text, nullable=False)
    highlighted_url: Mapped[str] = mapped_column(Text, nullable=True)
    canonical_key: Mapped[str] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
    expires_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False
    )

    view_count: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=SERVER_DEFAULT_ZERO, default=0
    )
    upvote_count: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=SERVER_DEFAULT_ZERO, default=0
    )
    downvote_count: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=SERVER_DEFAULT_ZERO, default=0
    )
    reference_count: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=SERVER_DEFAULT_ZERO, default=0
    )

    status: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default=ACTIVE_STATUS, default=ACTIVE_STATUS
    )
    is_hidden: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=SERVER_DEFAULT_FALSE, nullable=False
    )
    hidden_reason: Mapped[str] = mapped_column(Text, nullable=True)

    source: Mapped[str] = mapped_column(
        String(50), nullable=False, server_default=SNIPPET_SOURCE_DEFAULT, default=SNIPPET_SOURCE_DEFAULT
    )
    source_hash: Mapped[str] = mapped_column(String(64), nullable=False)

    __table_args__ = (
        Index(IDX_SNIPPETS_EXPIRES_AT, expires_at),
        Index(IDX_SNIPPETS_CREATED_AT, created_at.desc()),
        Index(IDX_SNIPPETS_UPVOTES, upvote_count.desc()),
        Index(IDX_SNIPPETS_TAGS, tags, postgresql_using=POSTGRES_USING_GIN),
        Index(IDX_SNIPPETS_STATUS, status),
        Index(IDX_SNIPPETS_SOURCE_HASH, source, source_hash, unique=True),
        Index(IDX_SNIPPETS_VISIBILITY, status, expires_at, is_hidden),
        Index(IDX_SNIPPETS_LANGUAGE, language),
        Index(IDX_SNIPPETS_KIND, kind),
        Index(IDX_SNIPPETS_CANONICAL, source, canonical_key),
    )


class SnippetEmbedding(Base):
    __tablename__ = TABLE_SNIPPET_EMBEDDINGS

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    snippet_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(FK_SNIPPETS_ID, ondelete=FK_ONDELETE_CASCADE),
        nullable=False,
    )

    vector: Mapped[list[float]] = mapped_column(Vector(384), nullable=False)
    embedding_model: Mapped[str] = mapped_column(Text, nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        Index(IDX_SNIPPET_EMBEDDINGS_SNIPPET_ID, snippet_id),
        Index(
            IDX_SNIPPET_EMBEDDINGS_VECTOR,
            vector,
            postgresql_using=POSTGRES_USING_HNSW,
            postgresql_ops={POSTGRES_VECTOR_OPS_KEY: POSTGRES_VECTOR_OPS_VALUE},
        ),
    )


class Stats(Base):
    __tablename__ = TABLE_STATS

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    total_snippets: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default=SERVER_DEFAULT_ZERO)
    total_views: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default=SERVER_DEFAULT_ZERO)
    total_upvotes: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default=SERVER_DEFAULT_ZERO)
    total_downvotes: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default=SERVER_DEFAULT_ZERO)
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class SnippetReference(Base):
    __tablename__ = TABLE_SNIPPET_REFERENCES

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    parent_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(FK_SNIPPETS_ID, ondelete=FK_ONDELETE_CASCADE),
        nullable=False,
    )
    child_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(FK_SNIPPETS_ID, ondelete=FK_ONDELETE_CASCADE),
        nullable=False,
    )
    version: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        server_default=SERVER_DEFAULT_ONE,
        default=1,
    )
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    __table_args__ = (
        Index(IDX_SNIPPET_REFERENCES_PARENT, parent_id),
        Index(IDX_SNIPPET_REFERENCES_CHILD, child_id),
    )
