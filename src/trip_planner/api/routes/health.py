from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from trip_planner.core.database import get_db

router = APIRouter(tags=["health"])

DbSession = Annotated[AsyncSession, Depends(get_db)]


@router.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "service": "trip-planner"}


@router.get("/health/db")
async def health_db(db: DbSession) -> dict[str, str]:
    await db.execute(text("SELECT 1"))
    return {"status": "ok", "database": "reachable"}
