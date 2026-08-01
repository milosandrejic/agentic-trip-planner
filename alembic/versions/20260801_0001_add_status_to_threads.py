"""add status to threads

Revision ID: 20260801_0001
Revises: 20260610_0003
Create Date: 2026-08-01

"""
from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "20260801_0001"
down_revision: Union[str, None] = "20260610_0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "threads",
        sa.Column(
            "status",
            sa.Enum(
                "pending",
                "running",
                "ready",
                "failed",
                "deleted",
                name="thread_status",
                native_enum=False,
                length=16,
            ),
            nullable=False,
            server_default="pending",
        ),
    )


def downgrade() -> None:
    op.drop_column("threads", "status")
