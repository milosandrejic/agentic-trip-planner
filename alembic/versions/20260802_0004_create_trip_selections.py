"""create selected_flights and selected_hotels tables

Revision ID: 20260802_0004
Revises: 20260802_0003
Create Date: 2026-08-02

"""
from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "20260802_0004"
down_revision: Union[str, None] = "20260802_0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "selected_flights",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("trip_id", sa.UUID(), nullable=False),
        sa.Column("flight", postgresql.JSONB(), nullable=False),
        sa.Column("selected_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["trip_id"], ["trips.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_selected_flights_trip_id", "selected_flights", ["trip_id"], unique=True)

    op.create_table(
        "selected_hotels",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("trip_id", sa.UUID(), nullable=False),
        sa.Column("hotel", postgresql.JSONB(), nullable=False),
        sa.Column("selected_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["trip_id"], ["trips.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_selected_hotels_trip_id", "selected_hotels", ["trip_id"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_selected_hotels_trip_id", table_name="selected_hotels")
    op.drop_table("selected_hotels")

    op.drop_index("ix_selected_flights_trip_id", table_name="selected_flights")
    op.drop_table("selected_flights")
