import enum
import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, Enum as SqlEnum, ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from trip_planner.core.database import Base

if TYPE_CHECKING:
    from trip_planner.models.message import Message


class ThreadStatus(str, enum.Enum):
    """Lifecycle state of a thread's planning run."""
    PENDING = "pending"
    RUNNING = "running"
    READY = "ready"
    FAILED = "failed"
    DELETED = "deleted"


def _thread_status_values(enum_type: type[ThreadStatus]) -> list[str]:
    """Persist the lowercase status values rather than the uppercase member names."""
    return [member.value for member in enum_type]


class Thread(Base):
    __tablename__ = "threads"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    slug: Mapped[str] = mapped_column(String(255), nullable=False, unique=True, index=True)
    status: Mapped[ThreadStatus] = mapped_column(
        SqlEnum(
            ThreadStatus,
            native_enum=False,
            length=16,
            values_callable=_thread_status_values,
        ),
        nullable=False,
        default=ThreadStatus.PENDING,
        server_default=ThreadStatus.PENDING.value,
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )

    messages: Mapped[list["Message"]] = relationship(
        "Message",
        back_populates="thread",
    )
