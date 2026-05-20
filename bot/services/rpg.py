"""RPG engine — XP/GP calculation, levelling, skill progression."""
from __future__ import annotations

import logging
import math
from datetime import date, datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.database.models import (
    CompletionStatus,
    DailyLog,
    TaskPriority,
    TaskTag,
    User,
    UserProfile,
    UserSkill,
)
from bot.kafka import publish, topics

logger = logging.getLogger(__name__)

# ── XP / GP tables ────────────────────────────────────────────────────────────

XP_BASE: dict[str, int] = {
    "work": 80, "learning": 70, "health": 60,
    "creative": 65, "admin": 50, "social": 45,
    "habit": 40, "none": 30,
}
GP_BASE: dict[str, int] = {
    "work": 60, "learning": 50, "health": 45,
    "creative": 55, "admin": 40, "social": 35,
    "habit": 30, "none": 20,
}
PRIORITY_MULT: dict[str, float] = {
    "P1": 3.0, "P2": 2.0, "P3": 1.5, "P4": 1.0,
}

# Todoist priority integer → our P-label (Todoist stores 4=urgent, 1=normal)
TODOIST_PRIO_MAP = {4: "P1", 3: "P2", 2: "P3", 1: "P4"}

# Skill tag mapping: internal tag → skill column name
TAG_TO_SKILL: dict[str, str] = {
    "work": "work", "learning": "learning", "health": "health",
    "creative": "creative", "admin": "admin", "social": "social",
    "habit": "habit",
}

# Level title bands
LEVEL_TITLES = [
    (1, 5, "Novice"), (6, 10, "Apprenti"), (11, 20, "Aventurier"),
    (21, 30, "Vétéran"), (31, 40, "Expert"), (41, 50, "Maître"),
]

MAX_SKILL_POINTS = 100
MAX_LEVEL = 50


def xp_required(level: int) -> int:
    """XP needed to reach `level` from level-1 cumulative baseline."""
    return int(100 * (level ** 1.8))


def level_for_xp(total_xp: int) -> int:
    for lvl in range(MAX_LEVEL, 0, -1):
        if total_xp >= xp_required(lvl):
            return lvl
    return 1


def title_for_level(level: int) -> str:
    for lo, hi, title in LEVEL_TITLES:
        if lo <= level <= hi:
            return title
    return "Maître"


def compute_xp_gp(tag: str, priority: str) -> tuple[int, int]:
    mult = PRIORITY_MULT.get(priority, 1.0)
    xp = int(XP_BASE.get(tag, XP_BASE["none"]) * mult)
    gp = int(GP_BASE.get(tag, GP_BASE["none"]) * mult)
    return xp, gp


async def apply_task_completion(
    session: AsyncSession,
    user: User,
    log: DailyLog,
    now: datetime | None = None,
) -> tuple[int, int, bool, bool]:
    """
    Award XP and GP for a completed task.

    Returns (xp_awarded, gp_awarded, levelled_up, skilled_up).
    """
    now = now or datetime.now(timezone.utc)
    profile = user.profile
    tag = log.tag.value if isinstance(log.tag, TaskTag) else log.tag
    priority = log.priority.value if isinstance(log.priority, TaskPriority) else log.priority

    base_xp, base_gp = compute_xp_gp(tag, priority)

    # Apply sleep modifier
    xp = int(base_xp * profile.sleep_xp_modifier)
    gp = int(base_gp * (1 + profile.sleep_gp_bonus_pct / 100))

    # Apply active XP boost (time-limited)
    if profile.xp_multiplier_until and profile.xp_multiplier_until > now:
        xp = int(xp * profile.xp_multiplier)
    if profile.gp_multiplier and profile.gp_multiplier != 1.0:
        gp = int(gp * profile.gp_multiplier)

    # Penalty modifier from tomorrow's penalty (applied at the moment of earning)
    penalty = await _get_todays_penalty_pct(session, user.id, now.date())
    if penalty > 0:
        xp = int(xp * (1 - penalty / 100))

    # Vétéran perk: +10 GP fixed for P1 tasks
    if log.priority in ("P1", TaskPriority.P1) and profile.level >= 21:
        gp += 10

    # Early bird bonus
    if _is_early_bird(now):
        gp += 20

    # Night owl bonus
    if _is_night_owl(now) and not await _night_owl_used_today(session, user.id, now.date()):
        xp += 10

    # Skill XP (savoir weekly double)
    if tag == "learning" and await _savoir_weekly_first(session, user):
        xp *= 2

    # Persist xp/gp to log
    log.xp_earned = xp
    log.gp_earned = gp
    session.add(log)

    old_level = profile.level
    profile.xp += xp
    profile.gp = max(0, profile.gp + gp)
    new_level = level_for_xp(profile.xp)
    profile.level = new_level
    session.add(profile)

    # Update skill
    skilled_up = await _increment_skill(session, user, tag)

    levelled_up = new_level > old_level
    if levelled_up:
        await publish(topics.RPG_EVENTS, topics.LEVEL_UP, {
            "discord_id": user.discord_id,
            "old_level": old_level,
            "new_level": new_level,
            "title": title_for_level(new_level),
        })

    await publish(topics.PRODUCTIVITY_EVENTS, topics.TASK_COMPLETED_RPG, {
        "discord_id": user.discord_id,
        "task_id": log.todoist_task_id,
        "task_name": log.task_name,
        "tag": tag,
        "priority": priority,
        "xp": xp,
        "gp": gp,
    })

    return xp, gp, levelled_up, skilled_up


async def _get_todays_penalty_pct(session: AsyncSession, user_id: int, today: date) -> float:
    from bot.database.models import PenaltyRecord
    result = await session.execute(
        select(PenaltyRecord).where(
            PenaltyRecord.user_id == user_id,
            PenaltyRecord.record_date == today,
        )
    )
    rec = result.scalar_one_or_none()
    return rec.xp_penalty_pct if rec else 0.0


async def _increment_skill(session: AsyncSession, user: User, tag: str) -> bool:
    skill_name = TAG_TO_SKILL.get(tag)
    if not skill_name:
        return False

    result = await session.execute(
        select(UserSkill).where(
            UserSkill.user_id == user.id,
            UserSkill.tag == tag,
        )
    )
    skill = result.scalar_one_or_none()
    if not skill:
        skill = UserSkill(user_id=user.id, tag=tag, points=0)
        session.add(skill)

    old = skill.points
    skill.points = min(MAX_SKILL_POINTS, skill.points + 1)
    skilled_up = old < skill.points and skill.points in (50, 100)

    if skilled_up:
        await publish(topics.RPG_EVENTS, topics.SKILL_UP, {
            "discord_id": user.discord_id,
            "skill": tag,
            "points": skill.points,
        })
    return skilled_up


def _is_early_bird(dt: datetime) -> bool:
    return dt.hour < 9


def _is_night_owl(dt: datetime) -> bool:
    return 22 <= dt.hour < 24 and not (dt.hour == 23 and dt.minute >= 55)


async def _night_owl_used_today(session: AsyncSession, user_id: int, today: date) -> bool:
    result = await session.execute(
        select(DailyLog).where(
            DailyLog.user_id == user_id,
            DailyLog.log_date == today,
            DailyLog.completed == True,  # noqa: E712
            DailyLog.xp_earned > 0,
        )
    )
    # Check if any log completed in night-owl window today
    rows = result.scalars().all()
    for row in rows:
        if row.completed_at and 22 <= row.completed_at.hour < 24:
            return True
    return False


async def _savoir_weekly_first(session: AsyncSession, user: User) -> bool:
    """True if this is the first dev/learning task completed today (weekly double, 1×/week)."""
    profile = user.profile
    today = date.today()
    if profile.next_xp_multiplier_use and profile.next_xp_multiplier_use > today:
        return False
    # Mark used for next 7 days
    from datetime import timedelta
    profile.next_xp_multiplier_use = today + timedelta(days=7)
    session.add(profile)
    return True


async def check_combo_bonus(session: AsyncSession, user: User, today: date) -> bool:
    """Award +50 XP if 3 different tags were completed today."""
    result = await session.execute(
        select(DailyLog.tag).where(
            DailyLog.user_id == user.id,
            DailyLog.log_date == today,
            DailyLog.completed == True,  # noqa: E712
        ).distinct()
    )
    tags = [r for r in result.scalars().all() if r != "none"]
    if len(tags) >= 3:
        user.profile.xp += 50
        session.add(user.profile)
        return True
    return False
