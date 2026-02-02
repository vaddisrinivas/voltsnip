"""add_pgvector_normalized

Revision ID: 21662ca26ad4
Revises: 6ebcab9b5445
Create Date: 2026-01-31 15:28:27.352382

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
import pgvector

# revision identifiers, used by Alembic.
revision: str = "21662ca26ad4"
down_revision: Union[str, Sequence[str], None] = "6ebcab9b5445"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Enable pgvector extension
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    # Create normalized table for embeddings
    op.create_table(
        "snippet_embeddings",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("snippet_id", sa.UUID(), nullable=False),
        sa.Column("vector", pgvector.sqlalchemy.vector.VECTOR(dim=384), nullable=False),
        sa.Column("embedding_model", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            postgresql.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["snippet_id"], ["snippets.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )

    # Create indexes for the new table
    op.create_index(
        "idx_snippet_embeddings_snippet_id",
        "snippet_embeddings",
        ["snippet_id"],
        unique=False,
    )
    op.create_index(
        "idx_snippet_embeddings_vector",
        "snippet_embeddings",
        ["vector"],
        unique=False,
        postgresql_using="ivfflat",
        postgresql_ops={"vector": "vector_cosine_ops"},
    )

    # Remove legacy columns from snippets table
    op.drop_column("snippets", "embedding_model")
    op.drop_column("snippets", "vector_id")


def downgrade() -> None:
    """Downgrade schema."""
    op.add_column(
        "snippets",
        sa.Column("vector_id", sa.TEXT(), autoincrement=False, nullable=True),
    )
    op.add_column(
        "snippets",
        sa.Column("embedding_model", sa.TEXT(), autoincrement=False, nullable=True),
    )

    op.drop_index(
        "idx_snippet_embeddings_vector",
        table_name="snippet_embeddings",
        postgresql_using="ivfflat",
        postgresql_ops={"vector": "vector_cosine_ops"},
    )
    op.drop_index("idx_snippet_embeddings_snippet_id", table_name="snippet_embeddings")
    op.drop_table("snippet_embeddings")
