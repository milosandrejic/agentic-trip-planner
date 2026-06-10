# pyright: reportPrivateUsage=false, reportUnknownMemberType=false, reportUnknownVariableType=false
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from trip_planner.tools.weather import _fetch_coordinates, _fetch_forecast, weather_tool

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


async def test_fetch_forecast_returns_formatted_lines() -> None:
    mock_response = _make_mock_response(_FORECAST_RESPONSE)

    with patch("trip_planner.tools.weather.httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = AsyncMock(return_value=mock_response)

        lines = await _fetch_forecast(48.8566, 2.3522, "2024-07-01", "2024-07-02")

    assert len(lines) == 2
    assert "28.5°C" in lines[0]
    assert "18.0°C" in lines[0]
    assert "0.0mm" in lines[0]
    # None values render as N/A
    assert "N/A" in lines[1]
    assert "5.2mm" in lines[1]


async def test_weather_tool_returns_full_forecast_string() -> None:
    with (
        patch("trip_planner.tools.weather._fetch_coordinates", new_callable=AsyncMock) as mock_coords,
        patch("trip_planner.tools.weather._fetch_forecast", new_callable=AsyncMock) as mock_forecast,
    ):
        mock_coords.return_value = (48.8566, 2.3522)
        mock_forecast.return_value = ["  2024-07-01: High 28.5°C, Low 18.0°C, Precipitation 0.0mm"]

        result = await weather_tool.ainvoke(
            {"city": "Paris", "start_date": "2024-07-01", "end_date": "2024-07-01"}
        )

    assert "Weather forecast for Paris:" in result
    assert "28.5°C" in result
