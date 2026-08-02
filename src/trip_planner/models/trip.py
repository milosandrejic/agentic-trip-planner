import enum
import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, Enum as SqlEnum, ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from trip_planner.core.database import Base

if TYPE_CHECKING:
    from trip_planner.models.thread import Thread


class TripStatus(str, enum.Enum):
    """Lifecycle state of a trip. Transition rules are enforced separately."""
    DRAFT = "draft"
    GENERATING = "generating"
    READY = "ready"
    COMPLETED = "completed"
    ARCHIVED = "archived"


def _trip_status_values(enum_type: type[TripStatus]) -> list[str]:
    """Persist the lowercase status values rather than the uppercase member names."""
    return [member.value for member in enum_type]


class Trip(Base):
    __tablename__ = "trips"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    slug: Mapped[str] = mapped_column(String(255), nullable=False, unique=True, index=True)
    destination: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[TripStatus] = mapped_column(
        SqlEnum(
            TripStatus,
            native_enum=False,
            length=16,
            values_callable=_trip_status_values,
        ),
        nullable=False,
        default=TripStatus.DRAFT,
        server_default=TripStatus.DRAFT.value,
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )

    thread: Mapped["Thread | None"] = relationship(
        "Thread",
        back_populates="trip",
        uselist=False,
    )
