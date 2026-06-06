from fastapi import APIRouter

from trip_planner.api.dependencies import CurrentUser
from trip_planner.models.user import User
from trip_planner.schemas.auth import UserResponse

router = APIRouter(prefix="/me", tags=["users"])


@router.get("", response_model=UserResponse)
async def get_me(current_user: CurrentUser) -> User:
    """Return the authenticated user's profile."""
    return current_user
