"""OpenWeatherMap API client for running-slot optimisation."""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

import aiohttp

from bot.config import get_settings

logger = logging.getLogger(__name__)

OWM_BASE = "https://api.openweathermap.org/data/2.5"

# "good running" thresholds
_TEMP_MIN = 5     # °C
_TEMP_MAX = 25    # °C
_MAX_WIND = 10    # m/s
_MAX_RAIN = 1     # mm/h
_GOOD_CODES = {800, 801, 802}  # clear / few clouds / scattered clouds


async def get_forecast(lat: float, lon: float) -> list[dict[str, Any]]:
    """Return 5-day / 3-hour forecast entries."""
    settings = get_settings()
    async with aiohttp.ClientSession() as s:
        async with s.get(
            f"{OWM_BASE}/forecast",
            params={
                "lat": lat,
                "lon": lon,
                "appid": settings.openweather_api_key,
                "units": "metric",
            },
        ) as resp:
            resp.raise_for_status()
            data = await resp.json()
    return data.get("list", [])


def best_running_slots(
    forecast: list[dict[str, Any]],
    free_slots: list[tuple[datetime, datetime]],
) -> list[dict[str, Any]]:
    """Intersect forecast good-weather windows with calendar free slots."""
    results = []
    for entry in forecast:
        dt = datetime.fromtimestamp(entry["dt"])
        temp = entry["main"]["temp"]
        wind = entry["wind"]["speed"]
        rain = entry.get("rain", {}).get("1h", 0)
        code = entry["weather"][0]["id"]

        is_good = (
            _TEMP_MIN <= temp <= _TEMP_MAX
            and wind <= _MAX_WIND
            and rain <= _MAX_RAIN
            and code in _GOOD_CODES
        )
        if not is_good:
            continue

        slot_start = dt
        slot_end = datetime.fromtimestamp(entry["dt"] + 3600)
        for free_start, free_end in free_slots:
            if free_start <= slot_start < free_end:
                results.append({
                    "start": slot_start,
                    "end": min(slot_end, free_end),
                    "temp": temp,
                    "wind": wind,
                    "description": entry["weather"][0]["description"].capitalize(),
                })
    return results
