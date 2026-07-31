# pyright: reportMissingTypeStubs=false, reportUnknownMemberType=false, reportUnknownVariableType=false, reportUnknownArgumentType=false
import time
from typing import Any

import httpx
from langchain_core.tools import tool
from pydantic import BaseModel

from trip_planner.services.types import ToolResult, WeatherDay, WeatherResult

_GEOCODING_URL = "https://geocoding-api.open-meteo.com/v1/search"
_FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
_DAILY_VARIABLES = "temperature_2m_max,temperature_2m_min,precipitation_sum"
_PROVIDER = "open-meteo"


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


async def _fetch_daily(lat: float, lon: float, start_date: str, end_date: str) -> list[WeatherDay]:
    """Fetch daily high/low temperature and precipitation as typed WeatherDay entries."""
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

    days: list[WeatherDay] = []
    for i, date in enumerate(dates):
        days.append(
            WeatherDay(
                date=date,
                temp_max_c=max_temps[i],
                temp_min_c=min_temps[i],
                precipitation_mm=precipitation[i],
            )
        )

    return days


def _format_forecast(city: str, days: list[WeatherDay]) -> str:
    """Format typed daily weather entries into a human-readable summary for the LLM."""
    lines: list[str] = [f"Weather forecast for {city}:"]

    for day in days:
        max_t = f"{day.temp_max_c}°C" if day.temp_max_c is not None else "N/A"
        min_t = f"{day.temp_min_c}°C" if day.temp_min_c is not None else "N/A"
        precip = f"{day.precipitation_mm}mm" if day.precipitation_mm is not None else "N/A"
        lines.append(f"  {day.date}: High {max_t}, Low {min_t}, Precipitation {precip}")

    return "\n".join(lines)


@tool(args_schema=_WeatherInput, response_format="content_and_artifact")
async def weather_tool(
    city: str, start_date: str, end_date: str
) -> tuple[str, ToolResult[WeatherResult]]:
    """Get a daily weather forecast for a city between two dates (YYYY-MM-DD format)."""
    start = time.perf_counter()

    try:
        lat, lon = await _fetch_coordinates(city)
        days = await _fetch_daily(lat, lon, start_date, end_date)
    except ValueError as exc:
        content = f"Weather unavailable: {exc}"
        result: ToolResult[WeatherResult] = ToolResult[WeatherResult].fail(
            provider=_PROVIDER, message=content
        )
    except httpx.HTTPStatusError as exc:
        content = f"Weather unavailable: Open-Meteo returned {exc.response.status_code}"
        result = ToolResult[WeatherResult].fail(provider=_PROVIDER, message=content, retryable=True)
    else:
        payload = WeatherResult(location=city, latitude=lat, longitude=lon, days=days)
        content = _format_forecast(city, days)
        if days:
            result = ToolResult.ok(provider=_PROVIDER, data=payload)
        else:
            result = ToolResult[WeatherResult].empty(provider=_PROVIDER)

    result.latency_ms = round((time.perf_counter() - start) * 1000, 2)
    return content, result
