import pytest

from trip_planner.config import Settings

_STRONG_SECRET = "a" * 40


def _make_settings(**overrides: object) -> Settings:
    defaults: dict[str, object] = {
        "app_env": "production",
        "jwt_secret": _STRONG_SECRET,
        "openai_api_key": "sk-test",
    }
    defaults.update(overrides)

    return Settings(_env_file=None, **defaults)  # type: ignore[arg-type]


def test_assert_production_ready_aborts_on_default_secret() -> None:
    settings = _make_settings(jwt_secret="change-me-in-production")

    with pytest.raises(RuntimeError, match="jwt_secret"):
        settings.assert_production_ready()


def test_assert_production_ready_aborts_on_empty_secret() -> None:
    settings = _make_settings(jwt_secret="")

    with pytest.raises(RuntimeError, match="jwt_secret"):
        settings.assert_production_ready()


def test_assert_production_ready_aborts_on_short_secret() -> None:
    settings = _make_settings(jwt_secret="too-short")

    with pytest.raises(RuntimeError, match="at least 32 bytes"):
        settings.assert_production_ready()


def test_assert_production_ready_aborts_when_openai_key_missing() -> None:
    settings = _make_settings(openai_api_key="")

    with pytest.raises(RuntimeError, match="openai_api_key"):
        settings.assert_production_ready()


def test_assert_production_ready_reports_all_fatal_problems() -> None:
    settings = _make_settings(jwt_secret="", openai_api_key="")

    with pytest.raises(RuntimeError, match="jwt_secret.*openai_api_key"):
        settings.assert_production_ready()


def test_assert_production_ready_warns_on_missing_optional_keys() -> None:
    settings = _make_settings(geoapify_api_key="", google_places_api_key="key")

    warnings = settings.assert_production_ready()

    assert any("geoapify_api_key" in warning for warning in warnings)
    assert all("google_places_api_key" not in warning for warning in warnings)


def test_assert_production_ready_passes_when_fully_configured() -> None:
    settings = _make_settings(
        tavily_api_key="key",
        duffel_api_key="key",
        liteapi_key="key",
        geoapify_api_key="key",
        google_places_api_key="key",
    )

    assert settings.assert_production_ready() == []


def test_assert_production_ready_is_noop_outside_production() -> None:
    settings = _make_settings(app_env="development", jwt_secret="change-me-in-production", openai_api_key="")

    assert settings.assert_production_ready() == []
