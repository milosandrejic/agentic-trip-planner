# pyright: reportMissingTypeStubs=false, reportUnknownMemberType=false, reportUnknownVariableType=false, reportUnknownArgumentType=false
from typing import Any

import httpx
from langchain_core.tools import tool
from pydantic import BaseModel

_GEOCODING_URL = "https://geocoding-api.open-meteo.com/v1/search"
_FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
_DAILY_VARIABLES = "temperature_2m_max,temperature_2m_min,precipitation_sum"


class _WeatherInput(BaseModel):
    city: str
    start_date: str
    end_date: str


async def _fetch_coordinates(city: str) -> tuple[float, float]:
    """Resolve a city name to (latitude, longitude) via Open-Meteo geocoding."""
    params = {"name": city, "count": 1, "language": "en", "format": "json"}

    async with httpx.AsyncClient() as client:
        response = await client.get(_GEOCODING_URL, params=params, timeout=10.0)
        response.raise_for_status()

    data: dict[str, Any] = response.json()
    results: list[dict[str, Any]] = data.get("results") or []

    if not results:
        raise ValueError(f"City not found: {city!r}")

    first = results[0]
    return float(first["latitude"]), float(first["longitude"])


async def _fetch_forecast(lat: float, lon: float, start_date: str, end_date: str) -> list[str]:
    """Fetch daily high/low temperature and precipitation for a coordinate and date range."""
    params = {
        "latitude": lat,
        "longitude": lon,
        "daily": _DAILY_VARIABLES,
        "start_date": start_date,
        "end_date": end_date,
        "timezone": "auto",
    }

    async with httpx.AsyncClient() as client:
        response = await client.get(_FORECAST_URL, params=params, timeout=10.0)
        response.raise_for_status()

    data: dict[str, Any] = response.json()
    daily: dict[str, Any] = data["daily"]

    dates: list[str] = daily["time"]
    max_temps: list[float | None] = daily["temperature_2m_max"]
    min_temps: list[float | None] = daily["temperature_2m_min"]
    precipitation: list[float | None] = daily["precipitation_sum"]

    lines: list[str] = []
    for i, date in enumerate(dates):
        max_t = f"{max_temps[i]}°C" if max_temps[i] is not None else "N/A"
        min_t = f"{min_temps[i]}°C" if min_temps[i] is not None else "N/A"
        precip = f"{precipitation[i]}mm" if precipitation[i] is not None else "N/A"
        lines.append(f"  {date}: High {max_t}, Low {min_t}, Precipitation {precip}")

    return lines


@tool(args_schema=_WeatherInput)
async def weather_tool(city: str, start_date: str, end_date: str) -> str:
    """Get a daily weather forecast for a city between two dates (YYYY-MM-DD format)."""
    lat, lon = await _fetch_coordinates(city)
    forecast_lines = await _fetch_forecast(lat, lon, start_date, end_date)

    header = f"Weather forecast for {city}:"
    return "\n".join([header] + forecast_lines)
