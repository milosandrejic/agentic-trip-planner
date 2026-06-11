import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from trip_planner.models.thread import Thread


async def create_thread(
    db: AsyncSession,
    user_id: uuid.UUID,
    title: str,
    slug: str,
) -> Thread:
    """Persist a new thread row and return the refreshed instance."""
    thread = Thread(user_id=user_id, title=title, slug=slug)

    db.add(thread)
    await db.flush()
    await db.refresh(thread)

    return thread


async def get_by_id(db: AsyncSession, thread_id: uuid.UUID) -> Thread | None:
    """Return an active thread by its id, or None if not found or soft-deleted."""
    result = await db.execute(
        select(Thread).where(Thread.id == thread_id, Thread.deleted_at.is_(None))
    )

    return result.scalar_one_or_none()


async def get_by_slug(db: AsyncSession, slug: str) -> Thread | None:
    """Return an active thread by its slug, or None if not found or soft-deleted."""
    result = await db.execute(
        select(Thread).where(Thread.slug == slug, Thread.deleted_at.is_(None))
    )

    return result.scalar_one_or_none()


async def list_by_user(db: AsyncSession, user_id: uuid.UUID) -> list[Thread]:
    """Return all active threads owned by the given user, newest first."""
    result = await db.execute(
        select(Thread)
        .where(Thread.user_id == user_id, Thread.deleted_at.is_(None))
        .order_by(Thread.updated_at.desc())
    )

    return list(result.scalars().all())


async def soft_delete(db: AsyncSession, thread: Thread) -> Thread:
    """Mark a thread as deleted and return the updated instance."""
    thread.deleted_at = datetime.now(timezone.utc)

    await db.flush()
    await db.refresh(thread)

    return thread
