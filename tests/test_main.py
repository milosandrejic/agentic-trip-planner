# pyright: reportPrivateUsage=false
import os
from contextlib import asynccontextmanager
from collections.abc import AsyncGenerator
from unittest.mock import AsyncMock, patch

from trip_planner.main import _configure_langsmith, app, lifespan


def test_configure_langsmith_sets_env_vars_when_enabled() -> None:
    fake_settings = {
        "langsmith_tracing": True,
        "langsmith_api_key": "test-key-123",
        "langsmith_project": "my-project",
    }

    with (
        patch("trip_planner.main.settings") as mock_settings,
        patch.dict(os.environ, {}, clear=False),
    ):
        mock_settings.langsmith_tracing = fake_settings["langsmith_tracing"]
        mock_settings.langsmith_api_key = fake_settings["langsmith_api_key"]
        mock_settings.langsmith_project = fake_settings["langsmith_project"]

        _configure_langsmith()

        assert os.environ.get("LANGCHAIN_TRACING_V2") == "true"
        assert os.environ.get("LANGCHAIN_API_KEY") == "test-key-123"
        assert os.environ.get("LANGCHAIN_PROJECT") == "my-project"


def test_configure_langsmith_does_not_set_env_vars_when_disabled() -> None:
    env_before = os.environ.copy()

    with patch("trip_planner.main.settings") as mock_settings:
        mock_settings.langsmith_tracing = False
        mock_settings.langsmith_api_key = ""

        _configure_langsmith()

    # No new LangChain vars added when disabled
    assert os.environ.get("LANGCHAIN_TRACING_V2", env_before.get("LANGCHAIN_TRACING_V2")) == env_before.get(
        "LANGCHAIN_TRACING_V2"
    )


async def test_lifespan_opens_and_closes_shared_http_client() -> None:
    mock_checkpointer = AsyncMock()

    @asynccontextmanager
    async def fake_conn(_url: str) -> AsyncGenerator[AsyncMock]:
        yield mock_checkpointer

    with (
        patch("trip_planner.main.AsyncPostgresSaver.from_conn_string", fake_conn),
        patch("trip_planner.main.init_graph") as mock_init,
        patch("trip_planner.main.open_http_client", new_callable=AsyncMock) as mock_open,
        patch("trip_planner.main.close_http_client", new_callable=AsyncMock) as mock_close,
    ):
        async with lifespan(app):
            mock_open.assert_awaited_once()
            mock_close.assert_not_awaited()

        mock_close.assert_awaited_once()

    mock_checkpointer.setup.assert_awaited_once()
    mock_init.assert_called_once_with(mock_checkpointer)
