"""initial_schema

Revision ID: 6ebcab9b5445
Revises:
Create Date: 2026-01-31 11:55:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import text
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "6ebcab9b5445"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Manual schema definition since we lack auto-generation env
    op.create_table(
        "snippets",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("title", sa.Text(), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("language", sa.String(length=50), nullable=True),
        sa.Column(
            "kind", sa.String(length=50), server_default="snippet", nullable=False
        ),
        sa.Column(
            "tags",
            postgresql.ARRAY(sa.String()),
            server_default=text("'{}'"),
            nullable=False,
        ),
        sa.Column("s3_key", sa.Text(), nullable=False),
        sa.Column("highlighted_url", sa.Text(), nullable=True),
        sa.Column("canonical_key", sa.Text(), nullable=True),
        sa.Column("vector_id", sa.Text(), nullable=True),
        sa.Column("embedding_model", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            postgresql.TIMESTAMP(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            postgresql.TIMESTAMP(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("expires_at", postgresql.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("view_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("upvote_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("downvote_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("reference_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column(
            "status", sa.String(length=16), server_default="active", nullable=False
        ),
        sa.Column("is_hidden", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("hidden_reason", sa.Text(), nullable=True),
        sa.Column(
            "source", sa.String(length=50), nullable=False, server_default="human"
        ),
        sa.Column("source_hash", sa.String(length=64), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )

    # Indexes
    op.create_index("idx_snippets_expires_at", "snippets", ["expires_at"], unique=False)
    op.create_index(
        "idx_snippets_created_at",
        "snippets",
        [sa.text("created_at DESC")],
        unique=False,
    )
    op.create_index(
        "idx_snippets_upvotes", "snippets", [sa.text("upvote_count DESC")], unique=False
    )
    op.create_index(
        "idx_snippets_tags", "snippets", ["tags"], unique=False, postgresql_using="gin"
    )
    op.create_index("idx_snippets_status", "snippets", ["status"], unique=False)
    op.create_index(
        "idx_snippets_source_hash", "snippets", ["source", "source_hash"], unique=True
    )
    op.create_index(
        "idx_snippets_visibility",
        "snippets",
        ["status", "expires_at", "is_hidden"],
        unique=False,
    )
    op.create_index("idx_snippets_language", "snippets", ["language"], unique=False)
    op.create_index("idx_snippets_kind", "snippets", ["kind"], unique=False)
    op.create_index(
        "idx_snippets_canonical", "snippets", ["source", "canonical_key"], unique=False
    )


def downgrade() -> None:
    op.drop_index("idx_snippets_canonical", table_name="snippets")
    op.drop_index("idx_snippets_kind", table_name="snippets")
    op.drop_index("idx_snippets_language", table_name="snippets")
    op.drop_index("idx_snippets_visibility", table_name="snippets")
    op.drop_index("idx_snippets_source_hash", table_name="snippets")
    op.drop_index("idx_snippets_status", table_name="snippets")
    op.drop_index("idx_snippets_tags", table_name="snippets", postgresql_using="gin")
    op.drop_index("idx_snippets_upvotes", table_name="snippets")
    op.drop_index("idx_snippets_created_at", table_name="snippets")
    op.drop_index("idx_snippets_expires_at", table_name="snippets")
    op.drop_table("snippets")
