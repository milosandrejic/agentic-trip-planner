"""create places table

Revision ID: 20260802_0003
Revises: 20260802_0002
Create Date: 2026-08-02

"""
from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "20260802_0003"
down_revision: Union[str, None] = "20260802_0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "places",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("provider", sa.String(32), nullable=False),
        sa.Column("external_id", sa.String(255), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("latitude", sa.Float(), nullable=True),
        sa.Column("longitude", sa.Float(), nullable=True),
        sa.Column("address", sa.String(512), nullable=True),
        sa.Column("metadata", postgresql.JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("provider", "external_id", name="uq_places_provider_external_id"),
    )


def downgrade() -> None:
    op.drop_table("places")
