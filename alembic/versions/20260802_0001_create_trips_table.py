"""create trips table and link threads

Revision ID: 20260802_0001
Revises: 20260801_0001
Create Date: 2026-08-02

"""
from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "20260802_0001"
down_revision: Union[str, None] = "20260801_0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "trips",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("slug", sa.String(255), nullable=False),
        sa.Column("destination", sa.Text(), nullable=True),
        sa.Column(
            "status",
            sa.Enum(
                "draft",
                "generating",
                "ready",
                "completed",
                "archived",
                name="trip_status",
                native_enum=False,
                length=16,
            ),
            nullable=False,
            server_default="draft",
        ),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_trips_user_id", "trips", ["user_id"])
    op.create_index("ix_trips_slug", "trips", ["slug"], unique=True)

    op.add_column("threads", sa.Column("trip_id", sa.UUID(), nullable=True))
    op.create_foreign_key(
        "fk_threads_trip_id_trips", "threads", "trips", ["trip_id"], ["id"]
    )
    op.create_index("ix_threads_trip_id", "threads", ["trip_id"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_threads_trip_id", table_name="threads")
    op.drop_constraint("fk_threads_trip_id_trips", "threads", type_="foreignkey")
    op.drop_column("threads", "trip_id")

    op.drop_index("ix_trips_slug", table_name="trips")
    op.drop_index("ix_trips_user_id", table_name="trips")
    op.drop_table("trips")
