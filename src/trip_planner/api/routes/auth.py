from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from trip_planner.core.database import get_db
from trip_planner.models.user import User
from trip_planner.repositories import user_repository
from trip_planner.schemas.auth import LoginRequest, RegisterRequest, TokenResponse, UserResponse
from trip_planner.services.auth_service import create_access_token, hash_password, verify_password

router = APIRouter(prefix="/auth", tags=["auth"])

DbSession = Annotated[AsyncSession, Depends(get_db)]


@router.post("/register", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def register(body: RegisterRequest, db: DbSession) -> User:
    """Register a new user. Returns the created user."""
    hashed = hash_password(body.password)

    try:
        user = await user_repository.create_user(
            db,
            email=body.email,
            hashed_password=hashed,
            first_name=body.first_name,
            last_name=body.last_name,
            country=body.country,
        )
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Email already registered",
        )

    return user


@router.post("/login", response_model=TokenResponse)
async def login(body: LoginRequest, db: DbSession) -> TokenResponse:
    """Authenticate a user. Returns a JWT access token."""
    user = await user_repository.get_user_by_email(db, body.email)

    if user is None or not verify_password(body.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
        )

    token = create_access_token(str(user.id))

    return TokenResponse(access_token=token)
