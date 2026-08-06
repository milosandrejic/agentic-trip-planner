# pyright: reportMissingTypeStubs=false
import os
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

from trip_planner.agents.graph import init_graph
from trip_planner.api.routes import auth, health, places, threads, trips, users
from trip_planner.config import get_settings
from trip_planner.logging_config import configure_logging, get_logger
from trip_planner.services.http_client import close_http_client, open_http_client

settings = get_settings()
configure_logging(settings.log_level)
log = get_logger(__name__)


def _configure_langsmith() -> None:
    if settings.langsmith_tracing and settings.langsmith_api_key:
        os.environ["LANGCHAIN_TRACING_V2"] = "true"
        os.environ["LANGCHAIN_API_KEY"] = settings.langsmith_api_key
        os.environ["LANGCHAIN_PROJECT"] = settings.langsmith_project


_configure_langsmith()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    for warning in settings.assert_production_ready():
        log.warning("config.warning", detail=warning)

    async with AsyncPostgresSaver.from_conn_string(settings.checkpoint_db_url) as checkpointer:
        await checkpointer.setup()
        init_graph(checkpointer)
        await open_http_client()

        log.info("app.startup", env=settings.app_env)

        try:
            yield
        finally:
            await close_http_client()
    log.info("app.shutdown")


app = FastAPI(
    title="Agentic Trip Planner",
    version="0.1.0",
    lifespan=lifespan,
)

app.include_router(health.router)
app.include_router(auth.router)
app.include_router(users.router)
app.include_router(trips.router)
app.include_router(threads.router)
app.include_router(places.router)
