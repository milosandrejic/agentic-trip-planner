from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # App
    app_env: Literal["development", "production", "test"] = "development"
    port: int = 8000
    log_level: str = "info"

    # Database
    database_url: str = Field(
        default="postgresql+asyncpg://trip_planner:trip_planner@localhost:5433/trip_planner",
    )

    # Auth (Phase 1)
    jwt_secret: str = "change-me-in-production"
    jwt_algorithm: str = "HS256"
    jwt_expire_hours: int = 24

    # LLM (Phase 2+)
    openai_api_key: str = ""
    openai_model: str = "gpt-4o-mini"

    # Tools (Phase 3)
    tavily_api_key: str = ""

    # Observability
    langsmith_tracing: bool = False
    langsmith_api_key: str = ""
    langsmith_project: str = "agentic-trip-planner"


@lru_cache
def get_settings() -> Settings:
    return Settings()
