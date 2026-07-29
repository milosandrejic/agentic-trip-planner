from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

_INSECURE_JWT_SECRETS = {"", "change-me-in-production"}
_MIN_JWT_SECRET_BYTES = 32


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

    # Travel APIs (Phase 5)
    duffel_api_key: str = ""
    liteapi_key: str = ""
    geoapify_api_key: str = ""
    google_places_api_key: str = ""

    # Observability
    langsmith_tracing: bool = False
    langsmith_api_key: str = ""
    langsmith_project: str = "agentic-trip-planner"

    @property
    def checkpoint_db_url(self) -> str:
        """psycopg3-compatible connection URL for the LangGraph checkpoint saver."""
        return self.database_url.replace("postgresql+asyncpg://", "postgresql://")

    def assert_production_ready(self) -> list[str]:
        """Fail fast on unsafe production configuration.

        Raises RuntimeError listing every fatal problem (default/weak JWT secret, missing
        required provider keys). Returns non-fatal warnings for optional provider keys that
        are unset. No-op outside production so development and tests stay lenient.
        """
        if self.app_env != "production":
            return []

        errors: list[str] = []

        secret_is_default = self.jwt_secret in _INSECURE_JWT_SECRETS
        secret_too_short = len(self.jwt_secret.encode("utf-8")) < _MIN_JWT_SECRET_BYTES

        if secret_is_default:
            errors.append("jwt_secret must be set to a strong, non-default value")
        elif secret_too_short:
            errors.append(f"jwt_secret must be at least {_MIN_JWT_SECRET_BYTES} bytes long")

        if not self.openai_api_key:
            errors.append("openai_api_key is required")

        if errors:
            joined_errors = "; ".join(errors)
            raise RuntimeError(f"Invalid production configuration: {joined_errors}")

        optional_provider_keys = {
            "tavily_api_key": self.tavily_api_key,
            "duffel_api_key": self.duffel_api_key,
            "liteapi_key": self.liteapi_key,
            "geoapify_api_key": self.geoapify_api_key,
            "google_places_api_key": self.google_places_api_key,
        }

        return [
            f"{name} is not set; the corresponding tool will be unavailable"
            for name, value in optional_provider_keys.items()
            if not value
        ]


@lru_cache
def get_settings() -> Settings:
    return Settings()
