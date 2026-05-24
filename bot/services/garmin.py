"""Garmin Health data client — garminconnect (unofficial Garmin Connect web API)."""
from __future__ import annotations

import asyncio
import logging
from datetime import date
from functools import partial
from typing import Any

from garminconnect import (
    Garmin,
    GarminConnectAuthenticationError,
    GarminConnectConnectionError,
)

logger = logging.getLogger(__name__)


async def connect(email: str, password: str) -> str:
    """Authenticate with Garmin Connect and return serialized garth token data."""
    def _login() -> str:
        api = Garmin(email, password)
        api.login()
        return api.garth.dumps()

    try:
        return await asyncio.get_event_loop().run_in_executor(None, _login)
    except GarminConnectAuthenticationError as e:
        raise ValueError(f"Email ou mot de passe incorrect : {e}") from e
    except GarminConnectConnectionError as e:
        raise ConnectionError(f"Impossible de joindre Garmin Connect : {e}") from e


class GarminClient:
    def __init__(self, token_data: str) -> None:
        self._token_data = token_data

    def _api(self) -> Garmin:
        api = Garmin()
        api.garth.loads(self._token_data)
        return api

    async def _run(self, fn, *args: Any) -> Any:
        return await asyncio.get_event_loop().run_in_executor(None, partial(fn, *args))

    def dump_token(self) -> str:
        """Return updated garth token JSON (captures any token refresh that occurred)."""
        return self._api().garth.dumps()

    async def get_daily_sleep(self, for_date: date) -> dict[str, Any]:
        api = self._api()
        data = await self._run(api.get_sleep_data, for_date.isoformat())
        return data if isinstance(data, dict) else {}

    async def get_sleep_score(self, for_date: date) -> dict[str, Any]:
        # Sleep score lives inside the same sleep data response
        return await self.get_daily_sleep(for_date)

    async def get_body_battery(self) -> list[dict[str, Any]]:
        api = self._api()
        today = date.today().isoformat()
        data = await self._run(api.get_body_battery, today, today)
        if not isinstance(data, list) or not data:
            return []
        # garminconnect: [{bodyBatteryValuesArray: [[timestamp_gmt, level, ...], ...]}]
        values = data[0].get("bodyBatteryValuesArray", [])
        return [{"bodyBattery": v[1]} for v in values if len(v) > 1]

    async def get_stress(self, for_date: date) -> dict[str, Any]:
        api = self._api()
        data = await self._run(api.get_stress_data, for_date.isoformat())
        if not isinstance(data, dict):
            return {"averageStressLevel": 25}
        values = data.get("stressValuesArray", [])
        valid = [v[1] for v in values if len(v) > 1 and v[1] >= 0]
        avg = int(sum(valid) / len(valid)) if valid else 25
        return {"averageStressLevel": avg}

    async def get_hrv(self, for_date: date) -> dict[str, Any]:
        api = self._api()
        try:
            data = await self._run(api.get_hrv_data, for_date.isoformat())
            summary = data.get("hrvSummary", {}) if isinstance(data, dict) else {}
            avg = summary.get("lastNightAvg") or 0
            return {"heartRateZones": [{"maxHeartRate": float(avg)}] if avg else []}
        except Exception:
            return {"heartRateZones": []}
