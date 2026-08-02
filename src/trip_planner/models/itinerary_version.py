import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import DateTime, ForeignKey, Integer, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from trip_planner.core.database import Base

if TYPE_CHECKING:
    from trip_planner.models.trip import Trip


class ItineraryVersion(Base):
    __tablename__ = "itinerary_versions"
    __table_args__ = (
        UniqueConstraint("trip_id", "version_number", name="uq_itinerary_versions_trip_version"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    trip_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("trips.id"), nullable=False, index=True
    )
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    itinerary: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )

    trip: Mapped["Trip"] = relationship(
        "Trip",
        back_populates="versions",
        foreign_keys=[trip_id],
    )
