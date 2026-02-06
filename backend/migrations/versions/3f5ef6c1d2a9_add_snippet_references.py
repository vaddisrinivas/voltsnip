"""add_snippet_references

Revision ID: 3f5ef6c1d2a9
Revises: 9b8c8c0b8a12
Create Date: 2026-02-05 13:10:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = "3f5ef6c1d2a9"
down_revision: Union[str, Sequence[str], None] = "9b8c8c0b8a12"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "snippet_references",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("parent_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("child_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column(
            "created_at",
            postgresql.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            postgresql.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["parent_id"], ["snippets.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["child_id"], ["snippets.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_index(
        "idx_snippet_references_parent",
        "snippet_references",
        ["parent_id"],
        unique=False,
    )
    op.create_index(
        "idx_snippet_references_child",
        "snippet_references",
        ["child_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("idx_snippet_references_child", table_name="snippet_references")
    op.drop_index("idx_snippet_references_parent", table_name="snippet_references")
    op.drop_table("snippet_references")
