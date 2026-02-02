from sqlalchemy import String, Integer, Text, Index, func, text, Boolean, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.dialects.postgresql import UUID, ARRAY, TIMESTAMP
from pgvector.sqlalchemy import Vector
from datetime import datetime
import uuid
from app.database import Base


class Snippet(Base):
    __tablename__ = "snippets"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    title: Mapped[str] = mapped_column(Text, nullable=True)
    description: Mapped[str] = mapped_column(Text, nullable=True)
    language: Mapped[str] = mapped_column(String(50), nullable=True)
    kind: Mapped[str] = mapped_column(
        String(50), nullable=False, server_default="snippet", default="snippet"
    )

    tags: Mapped[list[str]] = mapped_column(
        ARRAY(String), nullable=False, server_default=text("'{}'")
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
        Integer, nullable=False, server_default="0", default=0
    )
    upvote_count: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0", default=0
    )
    downvote_count: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0", default=0
    )
    reference_count: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0", default=0
    )

    status: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default="active", default="active"
    )
    is_hidden: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false", nullable=False
    )
    hidden_reason: Mapped[str] = mapped_column(Text, nullable=True)

    source: Mapped[str] = mapped_column(
        String(50), nullable=False, server_default="human", default="human"
    )
    source_hash: Mapped[str] = mapped_column(String(64), nullable=False)

    __table_args__ = (
        Index("idx_snippets_expires_at", "expires_at"),
        Index("idx_snippets_created_at", created_at.desc()),
        Index("idx_snippets_upvotes", upvote_count.desc()),
        Index("idx_snippets_tags", "tags", postgresql_using="gin"),
        Index("idx_snippets_status", "status"),
        Index("idx_snippets_source_hash", "source", "source_hash", unique=True),
        Index("idx_snippets_visibility", "status", "expires_at", "is_hidden"),
        Index("idx_snippets_language", "language"),
        Index("idx_snippets_kind", "kind"),
        Index("idx_snippets_canonical", "source", "canonical_key"),
    )


class SnippetEmbedding(Base):
    __tablename__ = "snippet_embeddings"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    snippet_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("snippets.id", ondelete="CASCADE"),
        nullable=False,
    )

    vector: Mapped[list[float]] = mapped_column(Vector(384), nullable=False)
    embedding_model: Mapped[str] = mapped_column(Text, nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        Index("idx_snippet_embeddings_snippet_id", "snippet_id"),
        Index(
            "idx_snippet_embeddings_vector",
            "vector",
            postgresql_using="hnsw",
            postgresql_ops={"vector": "vector_cosine_ops"},
        ),
    )
