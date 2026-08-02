import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from trip_planner.core.database import Base


class SelectedFlight(Base):
    """The flight option a trip has committed to, snapshotted from search results."""

    __tablename__ = "selected_flights"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    trip_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("trips.id"), nullable=False, unique=True, index=True
    )
    flight: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)

    selected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
