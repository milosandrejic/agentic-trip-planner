"""add is_active to users

Revision ID: 20260610_0003
Revises: 20260610_0002
Create Date: 2026-06-10

"""
from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "20260610_0003"
down_revision: Union[str, None] = "20260610_0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
    )


def downgrade() -> None:
    op.drop_column("users", "is_active")
