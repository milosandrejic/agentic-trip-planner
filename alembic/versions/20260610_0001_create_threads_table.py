"""create threads table

Revision ID: 20260610_0001
Revises: 20260530_0001
Create Date: 2026-06-10

"""
from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "20260610_0001"
down_revision: Union[str, None] = "20260530_0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "threads",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("slug", sa.String(255), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_threads_user_id", "threads", ["user_id"])
    op.create_index("ix_threads_slug", "threads", ["slug"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_threads_slug", table_name="threads")
    op.drop_index("ix_threads_user_id", table_name="threads")
    op.drop_table("threads")
