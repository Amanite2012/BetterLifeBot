"""Garmin sync worker — cron at 06h00 local time per user."""
from __future__ import annotations

import logging
from datetime import date, datetime, timezone

from sqlalchemy import select

from bot.database.connection import get_session
from bot.database.models import GarminToken, SleepLog, User
from bot.database.queries import get_user_by_id
from bot.kafka import publish, topics
from bot.services.encryption import decrypt
from bot.services.garmin import GarminClient

logger = logging.getLogger(__name__)


async def sync_user_garmin(user: User) -> None:
    """Fetch and persist today's Garmin sleep/battery data for one user."""
    async with get_session() as session:
        user = await get_user_by_id(session, user.id)
        if not user:
            return
        token = user.garmin_token
        if not token:
            return

        access_token = decrypt(token.access_token_enc)
        refresh_token = decrypt(token.refresh_token_enc)
        client = GarminClient(access_token, refresh_token)

        today = date.today()

        try:
            sleep_data = await client.get_daily_sleep(today)
            score_data = await client.get_sleep_score(today)
            battery_data = await client.get_body_battery()
            stress_data = await client.get_stress(today)
            hrv_data = await client.get_hrv(today)
        except Exception:
            logger.exception("Garmin API error for user %s", user.discord_id)
            return

        # Parse
        duration = sleep_data.get("dailySleepDTO", {}).get("sleepTimeSeconds", 0) // 60
        sleep_score = score_data.get("dailySleepDTO", {}).get("sleepScore", 0)
        body_battery = _latest_battery(battery_data)
        stress = stress_data.get("averageStressLevel", 25)
        hrv = _avg_hrv(hrv_data)
        cycles = sleep_data.get("dailySleepDTO", {}).get("deepSleepSeconds", 0) // 5400

        # Upsert SleepLog
        existing = await session.execute(
            select(SleepLog).where(SleepLog.user_id == user.id, SleepLog.sleep_date == today)
        )
        log = existing.scalar_one_or_none()
        if not log:
            log = SleepLog(user_id=user.id, sleep_date=today)

        log.duration_minutes = duration
        log.sleep_score = sleep_score
        log.body_battery = body_battery
        log.stress_level = stress
        log.hrv_avg = hrv
        log.sleep_cycles = max(0, cycles)
        session.add(log)

        # Update token last_sync
        token.last_sync = datetime.now(timezone.utc)
        session.add(token)

        # Apply RPG modifier for tomorrow based on sleep score
        await _apply_sleep_rpg_modifier(session, user, sleep_score)

    # Publish events
    await publish(topics.GARMIN_EVENTS, topics.SLEEP_LOGGED, {
        "discord_id": user.discord_id,
        "date": str(today),
        "sleep_score": sleep_score,
        "body_battery": body_battery,
    })

    if sleep_score < 40:
        await publish(topics.GARMIN_EVENTS, topics.SLEEP_ALERT, {
            "discord_id": user.discord_id,
            "sleep_score": sleep_score,
        })

    if body_battery < 20:
        await publish(topics.GARMIN_EVENTS, topics.BODY_BATTERY_LOW, {
            "discord_id": user.discord_id,
            "body_battery": body_battery,
        })

    logger.info(
        "Garmin sync done for user %s: score=%d battery=%d",
        user.discord_id, sleep_score, body_battery,
    )


async def run_all_garmin_syncs() -> None:
    """Called by APScheduler at 06h00 UTC — iterates all connected users."""
    async with get_session() as session:
        result = await session.execute(
            select(User).join(GarminToken, GarminToken.user_id == User.id)
        )
        users = result.scalars().all()

    logger.info("Starting Garmin sync for %d user(s)", len(users))
    for user in users:
        await sync_user_garmin(user)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _latest_battery(battery_data: list | dict) -> int:
    if isinstance(battery_data, list) and battery_data:
        return battery_data[-1].get("bodyBattery", 50)
    if isinstance(battery_data, dict):
        readings = battery_data.get("bodyBatteryReadingList", [])
        if readings:
            return readings[-1].get("bodyBatteryLevel", 50)
    return 50


def _avg_hrv(hrv_data: dict) -> float | None:
    readings = hrv_data.get("heartRateZones", [])
    if not readings:
        return None
    avg = sum(r.get("maxHeartRate", 0) for r in readings) / len(readings)
    return round(avg, 1)


async def _apply_sleep_rpg_modifier(session, user: User, sleep_score: int) -> None:
    profile = user.profile
    if sleep_score >= 90:
        profile.sleep_xp_modifier = 1.3
        profile.sleep_gp_bonus_pct = 15.0
    elif sleep_score >= 75:
        profile.sleep_xp_modifier = 1.1
        profile.sleep_gp_bonus_pct = 0.0
    elif sleep_score >= 60:
        profile.sleep_xp_modifier = 1.0
        profile.sleep_gp_bonus_pct = 0.0
    elif sleep_score >= 40:
        profile.sleep_xp_modifier = 0.9
        profile.sleep_gp_bonus_pct = 0.0
    else:
        profile.sleep_xp_modifier = 0.8
        profile.sleep_gp_bonus_pct = 0.0
    session.add(profile)
