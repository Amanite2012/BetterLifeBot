"""Garmin Health API client (OAuth 1.0a — Garmin uses OAuth 1 for third-party)."""
from __future__ import annotations

import logging
from datetime import date
from typing import Any

import aiohttp

from bot.config import get_settings
from bot.services.encryption import decrypt, encrypt

logger = logging.getLogger(__name__)

GARMIN_WELLNESS = "https://apis.garmin.com/wellness-api/rest"
GARMIN_AUTH_BASE = "https://connectapi.garmin.com"


class GarminClient:
    """Thin async wrapper around the Garmin Health SDK wellness endpoints."""

    def __init__(self, access_token: str, access_token_secret: str) -> None:
        self._token = access_token
        self._secret = access_token_secret

    def _oauth_header(self) -> dict[str, str]:
        # In production this would be a proper OAuth 1.0a signature.
        # We use a placeholder that must be replaced with a real OAuth lib
        # (e.g. requests-oauthlib adapted for aiohttp).
        return {"Authorization": f"Bearer {self._token}"}

    async def get_daily_sleep(self, for_date: date) -> dict[str, Any]:
        url = f"{GARMIN_WELLNESS}/dailySleep"
        async with aiohttp.ClientSession() as s:
            async with s.get(
                url,
                headers=self._oauth_header(),
                params={"uploadStartTimeInSeconds": _date_to_epoch(for_date)},
            ) as resp:
                resp.raise_for_status()
                return await resp.json()

    async def get_sleep_score(self, for_date: date) -> dict[str, Any]:
        url = f"{GARMIN_WELLNESS}/sleepScore"
        async with aiohttp.ClientSession() as s:
            async with s.get(
                url,
                headers=self._oauth_header(),
                params={"date": for_date.isoformat()},
            ) as resp:
                resp.raise_for_status()
                return await resp.json()

    async def get_body_battery(self) -> list[dict[str, Any]]:
        url = f"{GARMIN_WELLNESS}/bodyBattery"
        async with aiohttp.ClientSession() as s:
            async with s.get(url, headers=self._oauth_header()) as resp:
                resp.raise_for_status()
                return await resp.json()

    async def get_stress(self, for_date: date) -> dict[str, Any]:
        url = f"{GARMIN_WELLNESS}/stressLevel"
        async with aiohttp.ClientSession() as s:
            async with s.get(
                url,
                headers=self._oauth_header(),
                params={"date": for_date.isoformat()},
            ) as resp:
                resp.raise_for_status()
                return await resp.json()

    async def get_hrv(self, for_date: date) -> dict[str, Any]:
        url = f"{GARMIN_WELLNESS}/heartRateZones"
        async with aiohttp.ClientSession() as s:
            async with s.get(
                url,
                headers=self._oauth_header(),
                params={"date": for_date.isoformat()},
            ) as resp:
                resp.raise_for_status()
                return await resp.json()


def build_oauth_url() -> str:
    settings = get_settings()
    return (
        f"{GARMIN_AUTH_BASE}/oauth-service/oauth/authorize"
        f"?oauth_callback={settings.garmin_oauth_callback_url}"
    )


def _date_to_epoch(d: date) -> int:
    from datetime import datetime, timezone
    return int(datetime(d.year, d.month, d.day, tzinfo=timezone.utc).timestamp())
