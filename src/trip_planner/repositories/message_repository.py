import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from trip_planner.models.message import Message


async def create_message(
    db: AsyncSession,
    thread_id: uuid.UUID,
    role: str,
    content: str,
    itinerary: dict[str, Any] | None = None,
) -> Message:
    """Persist a new message row and return the refreshed instance."""
    message = Message(thread_id=thread_id, role=role, content=content, itinerary=itinerary)

    db.add(message)
    await db.flush()
    await db.refresh(message)

    return message


async def list_by_thread(
    db: AsyncSession,
    thread_id: uuid.UUID,
    *,
    before: datetime | None = None,
    limit: int = 20,
) -> list[Message]:
    """Return active messages for a thread, newest first, with cursor pagination.

    Pass `before` (a `created_at` value) to fetch the page preceding that timestamp.
    """
    query = select(Message).where(
        Message.thread_id == thread_id,
        Message.deleted_at.is_(None),
    )

    if before is not None:
        query = query.where(Message.created_at < before)

    query = query.order_by(Message.created_at.desc()).limit(limit)

    result = await db.execute(query)

    return list(result.scalars().all())


async def soft_delete_by_thread(db: AsyncSession, thread_id: uuid.UUID) -> None:
    """Soft-delete all messages belonging to a thread."""
    now = datetime.now(timezone.utc)

    messages_result = await db.execute(
        select(Message).where(Message.thread_id == thread_id, Message.deleted_at.is_(None))
    )
    messages = list(messages_result.scalars().all())

    for message in messages:
        message.deleted_at = now

    await db.flush()
