"""create itinerary_versions table and current version pointer

Revision ID: 20260802_0002
Revises: 20260802_0001
Create Date: 2026-08-02

"""
from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "20260802_0002"
down_revision: Union[str, None] = "20260802_0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "itinerary_versions",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("trip_id", sa.UUID(), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("itinerary", postgresql.JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["trip_id"], ["trips.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "trip_id", "version_number", name="uq_itinerary_versions_trip_version"
        ),
    )
    op.create_index("ix_itinerary_versions_trip_id", "itinerary_versions", ["trip_id"])
    op.create_index("ix_itinerary_versions_created_at", "itinerary_versions", ["created_at"])

    op.add_column("trips", sa.Column("current_version_id", sa.UUID(), nullable=True))
    op.create_foreign_key(
        "fk_trips_current_version_id_itinerary_versions",
        "trips",
        "itinerary_versions",
        ["current_version_id"],
        ["id"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "fk_trips_current_version_id_itinerary_versions", "trips", type_="foreignkey"
    )
    op.drop_column("trips", "current_version_id")

    op.drop_index("ix_itinerary_versions_created_at", table_name="itinerary_versions")
    op.drop_index("ix_itinerary_versions_trip_id", table_name="itinerary_versions")
    op.drop_table("itinerary_versions")
