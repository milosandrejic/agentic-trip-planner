# pyright: reportPrivateUsage=false
import os
from unittest.mock import patch

from trip_planner.main import _configure_langsmith


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
