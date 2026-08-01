import uuid
from datetime import datetime, timezone

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from trip_planner.models.thread import Thread, ThreadStatus


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


async def list_by_user(
    db: AsyncSession,
    user_id: uuid.UUID,
    *,
    cursor: tuple[datetime, uuid.UUID] | None = None,
    limit: int = 20,
) -> list[Thread]:
    """Return active threads owned by the user, newest first, with keyset pagination.

    Pass `cursor` (an `(updated_at, id)` pair) to fetch the page after that row.
    The composite key keeps paging stable when several rows share an `updated_at`.
    """
    query = select(Thread).where(Thread.user_id == user_id, Thread.deleted_at.is_(None))

    if cursor is not None:
        cursor_updated_at, cursor_id = cursor
        query = query.where(
            or_(
                Thread.updated_at < cursor_updated_at,
                and_(Thread.updated_at == cursor_updated_at, Thread.id < cursor_id),
            )
        )

    query = query.order_by(Thread.updated_at.desc(), Thread.id.desc()).limit(limit)

    result = await db.execute(query)

    return list(result.scalars().all())


async def soft_delete(db: AsyncSession, thread: Thread) -> Thread:
    """Mark a thread as deleted and return the updated instance."""
    thread.deleted_at = datetime.now(timezone.utc)
    thread.status = ThreadStatus.DELETED

    await db.flush()
    await db.refresh(thread)

    return thread
