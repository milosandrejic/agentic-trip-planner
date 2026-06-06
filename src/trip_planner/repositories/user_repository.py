import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from trip_planner.models.user import User


async def get_user_by_email(db: AsyncSession, email: str) -> User | None:
    """Return the user with the given email, or None if not found."""
    result = await db.execute(select(User).where(User.email == email))

    return result.scalar_one_or_none()


async def get_user_by_id(db: AsyncSession, user_id: uuid.UUID) -> User | None:
    """Return the user with the given id, or None if not found."""
    return await db.get(User, user_id)


async def create_user(
    db: AsyncSession,
    email: str,
    hashed_password: str,
    first_name: str,
    last_name: str,
    country: str | None,
) -> User:
    """Persist a new user row and return the refreshed instance."""
    user = User(
        email=email,
        hashed_password=hashed_password,
        first_name=first_name,
        last_name=last_name,
        country=country,
    )

    db.add(user)
    await db.flush()
    await db.refresh(user)

    return user
