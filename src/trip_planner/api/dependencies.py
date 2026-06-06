import uuid
from typing import Annotated

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from trip_planner.core.database import get_db
from trip_planner.models.user import User
from trip_planner.repositories import user_repository
from trip_planner.services.auth_service import decode_access_token

_bearer = HTTPBearer()

DbSession = Annotated[AsyncSession, Depends(get_db)]
BearerToken = Annotated[HTTPAuthorizationCredentials, Depends(_bearer)]

_credentials_error = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Invalid or expired token",
    headers={"WWW-Authenticate": "Bearer"},
)


async def require_token(credentials: BearerToken) -> str:
    """Validate JWT signature and expiry. Returns user_id str. No DB hit."""
    try:
        return decode_access_token(credentials.credentials)
    except jwt.InvalidTokenError:
        raise _credentials_error


ValidatedUserId = Annotated[str, Depends(require_token)]


async def get_current_user(user_id: ValidatedUserId, db: DbSession) -> User:
    """Fetch the User for an already-validated token. Raises 401 if user no longer exists."""
    user = await user_repository.get_user_by_id(db, uuid.UUID(user_id))

    if user is None:
        raise _credentials_error

    return user


CurrentUser = Annotated[User, Depends(get_current_user)]
