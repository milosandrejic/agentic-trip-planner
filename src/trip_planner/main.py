from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from trip_planner.api.routes import health
from trip_planner.config import get_settings
from trip_planner.logging_config import configure_logging, get_logger

settings = get_settings()
configure_logging(settings.log_level)
log = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    log.info("app.startup", env=settings.app_env)
    yield
    log.info("app.shutdown")


app = FastAPI(
    title="Agentic Trip Planner",
    version="0.1.0",
    lifespan=lifespan,
)

app.include_router(health.router)
