"""add_stats_table

Revision ID: 9b8c8c0b8a12
Revises: 2ed6df5a9dea
Create Date: 2026-02-05 12:45:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = "9b8c8c0b8a12"
down_revision: Union[str, Sequence[str], None] = "2ed6df5a9dea"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "stats",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("total_snippets", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("total_views", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("total_upvotes", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("total_downvotes", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "updated_at",
            postgresql.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("stats")
