"""Google Calendar API client for free-slot detection."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

import aiohttp

from bot.config import get_settings

logger = logging.getLogger(__name__)

GOOGLE_CALENDAR_API = "https://www.googleapis.com/calendar/v3"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"


def build_auth_url(state: str) -> str:
    settings = get_settings()
    params = (
        f"?client_id={settings.google_client_id}"
        f"&redirect_uri={settings.google_redirect_uri}"
        "&response_type=code"
        "&scope=https://www.googleapis.com/auth/calendar.readonly"
        f"&state={state}"
        "&access_type=offline"
        "&prompt=consent"
    )
    return GOOGLE_AUTH_URL + params


async def exchange_code(code: str) -> dict[str, Any]:
    settings = get_settings()
    async with aiohttp.ClientSession() as s:
        async with s.post(GOOGLE_TOKEN_URL, data={
            "code": code,
            "client_id": settings.google_client_id,
            "client_secret": settings.google_client_secret,
            "redirect_uri": settings.google_redirect_uri,
            "grant_type": "authorization_code",
        }) as resp:
            resp.raise_for_status()
            return await resp.json()


async def refresh_access_token(refresh_token: str) -> dict[str, Any]:
    settings = get_settings()
    async with aiohttp.ClientSession() as s:
        async with s.post(GOOGLE_TOKEN_URL, data={
            "refresh_token": refresh_token,
            "client_id": settings.google_client_id,
            "client_secret": settings.google_client_secret,
            "grant_type": "refresh_token",
        }) as resp:
            resp.raise_for_status()
            return await resp.json()


async def get_free_slots(
    access_token: str,
    day: datetime,
    slot_duration_minutes: int = 60,
) -> list[tuple[datetime, datetime]]:
    """Return list of (start, end) free time slots on the given day."""
    start_of_day = day.replace(hour=6, minute=0, second=0, microsecond=0)
    end_of_day = day.replace(hour=22, minute=0, second=0, microsecond=0)

    headers = {"Authorization": f"Bearer {access_token}"}
    async with aiohttp.ClientSession() as s:
        async with s.get(
            f"{GOOGLE_CALENDAR_API}/calendars/primary/events",
            headers=headers,
            params={
                "timeMin": start_of_day.isoformat(),
                "timeMax": end_of_day.isoformat(),
                "singleEvents": "true",
                "orderBy": "startTime",
            },
        ) as resp:
            resp.raise_for_status()
            data = await resp.json()

    busy: list[tuple[datetime, datetime]] = []
    for event in data.get("items", []):
        s_str = event.get("start", {}).get("dateTime")
        e_str = event.get("end", {}).get("dateTime")
        if s_str and e_str:
            busy.append((datetime.fromisoformat(s_str), datetime.fromisoformat(e_str)))

    return _compute_free_slots(start_of_day, end_of_day, busy, slot_duration_minutes)


def _compute_free_slots(
    start: datetime,
    end: datetime,
    busy: list[tuple[datetime, datetime]],
    duration_minutes: int,
) -> list[tuple[datetime, datetime]]:
    free: list[tuple[datetime, datetime]] = []
    cursor = start
    for b_start, b_end in sorted(busy):
        if cursor + timedelta(minutes=duration_minutes) <= b_start:
            free.append((cursor, b_start))
        cursor = max(cursor, b_end)
    if cursor + timedelta(minutes=duration_minutes) <= end:
        free.append((cursor, end))
    return free
