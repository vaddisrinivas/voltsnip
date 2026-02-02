"""rename s3_key to blob_key

Revision ID: 2ed6df5a9dea
Revises: 21662ca26ad4
Create Date: 2026-01-31 18:28:45.320863

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = '2ed6df5a9dea'
down_revision: Union[str, Sequence[str], None] = '21662ca26ad4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column('snippets', 's3_key', new_column_name='blob_key')


def downgrade() -> None:
    op.alter_column('snippets', 'blob_key', new_column_name='s3_key')
