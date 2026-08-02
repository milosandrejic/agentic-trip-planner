import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from trip_planner.core.database import Base


class Place(Base):
    """A provider-independent point of interest, keyed by (provider, external_id)."""

    __tablename__ = "places"
    __table_args__ = (
        UniqueConstraint("provider", "external_id", name="uq_places_provider_external_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    external_id: Mapped[str] = mapped_column(String(255), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    latitude: Mapped[float | None] = mapped_column(nullable=True)
    longitude: Mapped[float | None] = mapped_column(nullable=True)
    address: Mapped[str | None] = mapped_column(String(512), nullable=True)
    # "metadata" is reserved on the declarative base, so the attribute is renamed.
    place_metadata: Mapped[dict[str, Any]] = mapped_column("metadata", JSONB, nullable=False)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )
