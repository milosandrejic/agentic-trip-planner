# pyright: reportPrivateUsage=false, reportUnknownMemberType=false, reportUnknownVariableType=false
from collections.abc import Mapping
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from trip_planner.services.types import ToolStatus, WeatherDay
from trip_planner.tools.weather import _fetch_coordinates, _fetch_daily, weather_tool

_GEOCODING_RESPONSE = {
    "results": [
        {"latitude": 48.8566, "longitude": 2.3522, "name": "Paris"},
    ]
}

_GEOCODING_EMPTY_RESPONSE: dict[str, list[object]] = {"results": []}

_FORECAST_RESPONSE = {
    "daily": {
        "time": ["2024-07-01", "2024-07-02"],
        "temperature_2m_max": [28.5, None],
        "temperature_2m_min": [18.0, None],
        "precipitation_sum": [0.0, 5.2],
    }
}


def _make_mock_response(json_data: object, status_code: int = 200) -> MagicMock:
    response = MagicMock(spec=httpx.Response)
    response.status_code = status_code
    response.json.return_value = json_data
    response.raise_for_status = MagicMock()
    return response


async def test_fetch_coordinates_returns_lat_lon() -> None:
    mock_response = _make_mock_response(_GEOCODING_RESPONSE)

    with patch("trip_planner.tools.weather.httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = AsyncMock(return_value=mock_response)

        lat, lon = await _fetch_coordinates("Paris")

    assert lat == 48.8566
    assert lon == 2.3522


async def test_fetch_coordinates_raises_for_unknown_city() -> None:
    mock_response = _make_mock_response(_GEOCODING_EMPTY_RESPONSE)

    with patch("trip_planner.tools.weather.httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = AsyncMock(return_value=mock_response)

        with pytest.raises(ValueError, match="City not found"):
            await _fetch_coordinates("Atlantis")


async def test_fetch_daily_returns_typed_weather_days() -> None:
    mock_response = _make_mock_response(_FORECAST_RESPONSE)

    with patch("trip_planner.tools.weather.httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = AsyncMock(return_value=mock_response)

        days = await _fetch_daily(48.8566, 2.3522, "2024-07-01", "2024-07-02")

    assert len(days) == 2
    assert days[0].date == "2024-07-01"
    assert days[0].temp_max_c == 28.5
    assert days[0].temp_min_c == 18.0
    assert days[0].precipitation_mm == 0.0
    # None values are preserved
    assert days[1].temp_max_c is None
    assert days[1].precipitation_mm == 5.2


async def test_weather_tool_returns_full_forecast_string() -> None:
    with (
        patch("trip_planner.tools.weather._fetch_coordinates", new_callable=AsyncMock) as mock_coords,
        patch("trip_planner.tools.weather._fetch_daily", new_callable=AsyncMock) as mock_daily,
    ):
        mock_coords.return_value = (48.8566, 2.3522)
        mock_daily.return_value = [
            WeatherDay(
                date="2024-07-01", temp_max_c=28.5, temp_min_c=18.0, precipitation_mm=0.0
            )
        ]

        result = await weather_tool.ainvoke(
            {"city": "Paris", "start_date": "2024-07-01", "end_date": "2024-07-01"}
        )

    assert "Weather forecast for Paris:" in result
    assert "28.5°C" in result


async def test_weather_tool_returns_error_string_on_http_error() -> None:
    with patch("trip_planner.tools.weather._fetch_coordinates", new_callable=AsyncMock) as mock_coords:
        mock_coords.side_effect = httpx.HTTPStatusError(
            "400", request=MagicMock(), response=MagicMock(status_code=400)
        )

        result = await weather_tool.ainvoke(
            {"city": "Paris", "start_date": "2020-01-01", "end_date": "2020-01-03"}
        )

    assert "unavailable" in result
    assert "400" in result


async def test_weather_tool_returns_error_string_for_unknown_city() -> None:
    with patch("trip_planner.tools.weather._fetch_coordinates", new_callable=AsyncMock) as mock_coords:
        mock_coords.side_effect = ValueError("City not found: 'Atlantis'")

        result = await weather_tool.ainvoke(
            {"city": "Atlantis", "start_date": "2024-07-01", "end_date": "2024-07-03"}
        )

    assert "unavailable" in result
    assert "Atlantis" in result


# --- weather_tool ToolResult envelope ---

_SUCCESS_ARGS = {"city": "Paris", "start_date": "2024-07-01", "end_date": "2024-07-02"}


def _tool_call(args: Mapping[str, object]) -> dict[str, object]:
    return {"type": "tool_call", "name": "weather_tool", "args": args, "id": "call_1"}


async def test_weather_tool_success_envelope_carries_typed_days() -> None:
    with (
        patch("trip_planner.tools.weather._fetch_coordinates", new_callable=AsyncMock) as mock_coords,
        patch("trip_planner.tools.weather._fetch_daily", new_callable=AsyncMock) as mock_daily,
    ):
        mock_coords.return_value = (48.8566, 2.3522)
        mock_daily.return_value = [
            WeatherDay(date="2024-07-01", temp_max_c=28.5, temp_min_c=18.0, precipitation_mm=0.0)
        ]
        message = await weather_tool.ainvoke(_tool_call(_SUCCESS_ARGS))

    result = message.artifact
    assert result.status == ToolStatus.SUCCESS
    assert result.provider == "open-meteo"
    assert result.error is None
    assert result.latency_ms is not None
    assert result.data is not None
    assert result.data.location == "Paris"
    assert len(result.data.days) == 1


async def test_weather_tool_empty_envelope_when_no_days() -> None:
    with (
        patch("trip_planner.tools.weather._fetch_coordinates", new_callable=AsyncMock) as mock_coords,
        patch("trip_planner.tools.weather._fetch_daily", new_callable=AsyncMock) as mock_daily,
    ):
        mock_coords.return_value = (48.8566, 2.3522)
        mock_daily.return_value = []
        message = await weather_tool.ainvoke(_tool_call(_SUCCESS_ARGS))

    result = message.artifact
    assert result.status == ToolStatus.EMPTY
    assert result.provider == "open-meteo"
    assert result.data is None
    assert result.error is None
    assert result.latency_ms is not None


async def test_weather_tool_error_envelope_is_retryable_on_http_error() -> None:
    with patch("trip_planner.tools.weather._fetch_coordinates", new_callable=AsyncMock) as mock_coords:
        mock_coords.side_effect = httpx.HTTPStatusError(
            "503", request=MagicMock(), response=MagicMock(status_code=503)
        )
        message = await weather_tool.ainvoke(_tool_call(_SUCCESS_ARGS))

    result = message.artifact
    assert result.status == ToolStatus.ERROR
    assert result.provider == "open-meteo"
    assert result.data is None
    assert result.error is not None
    assert result.error.retryable is True


async def test_weather_tool_error_envelope_not_retryable_for_unknown_city() -> None:
    with patch("trip_planner.tools.weather._fetch_coordinates", new_callable=AsyncMock) as mock_coords:
        mock_coords.side_effect = ValueError("City not found: 'Atlantis'")
        message = await weather_tool.ainvoke(
            _tool_call({"city": "Atlantis", "start_date": "2024-07-01", "end_date": "2024-07-02"})
        )

    result = message.artifact
    assert result.status == ToolStatus.ERROR
    assert result.error is not None
    assert result.error.retryable is False
