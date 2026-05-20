"""Streak management service."""
from __future__ import annotations

import logging
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.database.models import HabitStreak, User
from bot.kafka import publish, topics

logger = logging.getLogger(__name__)


async def get_or_create_streak(
    session: AsyncSession, user: User, streak_type: str = "daily"
) -> HabitStreak:
    result = await session.execute(
        select(HabitStreak).where(
            HabitStreak.user_id == user.id,
            HabitStreak.streak_type == streak_type,
        )
    )
    streak = result.scalar_one_or_none()
    if not streak:
        streak = HabitStreak(user_id=user.id, streak_type=streak_type)
        session.add(streak)
    return streak


async def record_completion(
    session: AsyncSession, user: User, today: date, streak_type: str = "daily"
) -> HabitStreak:
    streak = await get_or_create_streak(session, user, streak_type)
    yesterday = today - timedelta(days=1)

    if streak.last_completed == yesterday:
        streak.current_streak += 1
    elif streak.last_completed == today:
        pass  # already counted today
    else:
        streak.current_streak = 1

    if streak.current_streak > streak.longest_streak:
        streak.longest_streak = streak.current_streak

    streak.last_completed = today
    session.add(streak)

    # Hebdo bonus: 7 days streak
    if streak.current_streak > 0 and streak.current_streak % 7 == 0:
        user.profile.xp_multiplier = 1.5
        from datetime import datetime, timezone
        from datetime import timedelta as td
        user.profile.xp_multiplier_until = datetime.now(timezone.utc) + td(hours=24)
        session.add(user.profile)
        await publish(topics.RPG_EVENTS, topics.STREAK_RPG_BONUS, {
            "discord_id": user.discord_id,
            "streak": streak.current_streak,
        })

    return streak


async def reset_streak(
    session: AsyncSession, user: User, streak_type: str = "daily"
) -> HabitStreak:
    streak = await get_or_create_streak(session, user, streak_type)

    # Check protection (Endurance skill)
    if streak.protected_until and streak.protected_until >= date.today():
        logger.info("Streak protected for user %s until %s", user.discord_id, streak.protected_until)
        return streak

    streak.current_streak = 0
    session.add(streak)
    await publish(topics.PENALTIES_EVENTS, topics.STREAK_BROKEN, {
        "discord_id": user.discord_id,
        "streak_type": streak_type,
    })
    return streak


async def apply_endurance_protection(
    session: AsyncSession, user: User, days: int = 7
) -> None:
    """Activate streak protection (Endurance skill @ 100 pts)."""
    streak = await get_or_create_streak(session, user, "sport")
    streak.protected_until = date.today() + timedelta(days=days)
    session.add(streak)


async def check_discipline_monthly_grace(
    session: AsyncSession, user: User, streak: HabitStreak
) -> bool:
    """Return True and mark used if the Discipline skill monthly grace is available."""
    today = date.today()
    if streak.monthly_grace_reset and streak.monthly_grace_reset.month == today.month:
        return False  # already used this month
    if streak.monthly_grace_used and (
        streak.monthly_grace_reset is None or streak.monthly_grace_reset.month != today.month
    ):
        # Reset monthly flag at month boundary
        streak.monthly_grace_used = False

    if not streak.monthly_grace_used:
        streak.monthly_grace_used = True
        streak.monthly_grace_reset = today
        session.add(streak)
        return True
    return False
