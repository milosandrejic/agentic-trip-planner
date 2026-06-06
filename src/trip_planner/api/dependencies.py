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


async def get_current_user(credentials: BearerToken, db: DbSession) -> User:
    """Resolve a Bearer JWT to the authenticated User.

    Raises 401 if the token is missing, invalid, expired, or the user no longer exists.
    """
    credentials_error = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid or expired token",
        headers={"WWW-Authenticate": "Bearer"},
    )

    try:
        user_id_str = decode_access_token(credentials.credentials)
    except jwt.InvalidTokenError:
        raise credentials_error

    user_id = uuid.UUID(user_id_str)
    user = await user_repository.get_user_by_id(db, user_id)

    if user is None:
        raise credentials_error

    return user


CurrentUser = Annotated[User, Depends(get_current_user)]
