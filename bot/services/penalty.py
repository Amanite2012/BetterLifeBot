"""Penalty calculation engine — §2.7 of the spec."""
from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.database.models import (
    CompletionStatus,
    DailyLog,
    GraceDay,
    PenaltyRecord,
    SleepLog,
    TaskPriority,
    User,
    VacationMode,
)
from bot.kafka import publish, topics
from bot.services.streak import get_or_create_streak, reset_streak

logger = logging.getLogger(__name__)

# Priority weights for completion calculation
PRIORITY_WEIGHT: dict[str, float] = {"P1": 4.0, "P2": 2.0, "P3": 1.0, "P4": 0.5}
PRIORITY_GP_PENALTY: dict[str, int] = {"P1": 30, "P2": 15, "P3": 0, "P4": 0}

# Recidivism multipliers (day → multiplier, capped at day 5)
RECIDIVE_MULT: dict[int, float] = {1: 1.0, 2: 1.3, 3: 1.6, 4: 2.0}
RECIDIVE_CAP = 2.5

DAILY_XP_PCT_CAP = 75.0
DAILY_GP_CAP = 100


def _prio(task: DailyLog) -> str:
    p = task.priority
    return p.value if isinstance(p, TaskPriority) else p


def compute_weighted_completion(
    all_tasks: list[DailyLog],
    completed_tasks: list[DailyLog],
) -> float:
    total_weight = sum(PRIORITY_WEIGHT.get(_prio(t), 1.0) for t in all_tasks)
    if total_weight == 0:
        return 100.0
    done_weight = sum(PRIORITY_WEIGHT.get(_prio(t), 1.0) for t in completed_tasks)
    return (done_weight / total_weight) * 100.0


def tier_for_pct(pct: float) -> CompletionStatus:
    if pct >= 100:
        return CompletionStatus.PERFECT
    if pct >= 75:
        return CompletionStatus.NEAR_COMPLETE
    if pct >= 50:
        return CompletionStatus.PARTIAL
    if pct >= 25:
        return CompletionStatus.INSUFFICIENT
    if pct > 0:
        return CompletionStatus.CRITICAL
    return CompletionStatus.ABANDONED


_TIER_XP_PCT: dict[CompletionStatus, float] = {
    CompletionStatus.PERFECT: 0.0,
    CompletionStatus.NEAR_COMPLETE: 5.0,
    CompletionStatus.PARTIAL: 15.0,
    CompletionStatus.INSUFFICIENT: 30.0,
    CompletionStatus.CRITICAL: 50.0,
    CompletionStatus.ABANDONED: 75.0,
}
_TIER_GP: dict[CompletionStatus, int] = {
    CompletionStatus.PERFECT: 0,
    CompletionStatus.NEAR_COMPLETE: 0,
    CompletionStatus.PARTIAL: 10,
    CompletionStatus.INSUFFICIENT: 25,
    CompletionStatus.CRITICAL: 50,
    CompletionStatus.ABANDONED: 100,
}


async def run_daily_audit(session: AsyncSession, user: User, today: date) -> PenaltyRecord:
    """
    Core audit function called by the 23h55 cron.
    Returns the PenaltyRecord created/updated for today.
    """
    # Check grace day
    grace_used = await _is_grace_day(session, user.id, today)
    # Check vacation mode
    on_vacation = await _is_on_vacation(session, user.id, today)

    if grace_used or on_vacation:
        rec = PenaltyRecord(
            user_id=user.id,
            record_date=today,
            weighted_completion_pct=100.0,
            status=CompletionStatus.PERFECT,
            xp_penalty_pct=0.0,
            gp_penalty=0,
            grace_day_used=grace_used,
            vacation_mode=on_vacation,
        )
        session.add(rec)
        await publish(topics.PENALTIES_EVENTS, topics.GRACE_DAY_USED, {"discord_id": user.discord_id, "date": str(today)})
        return rec

    # Fetch today's tasks
    result = await session.execute(
        select(DailyLog).where(DailyLog.user_id == user.id, DailyLog.log_date == today)
    )
    all_tasks = result.scalars().all()
    # Exclude @grace-labelled tasks — we store them with priority P4 weight 0
    eligible = [t for t in all_tasks]
    done = [t for t in eligible if t.completed]

    if not eligible:
        # No tasks → no penalty
        return PenaltyRecord(user_id=user.id, record_date=today, status=CompletionStatus.PERFECT)

    pct = compute_weighted_completion(eligible, done)
    status = tier_for_pct(pct)

    xp_pct = _TIER_XP_PCT[status]
    gp_penalty = _TIER_GP[status]

    # Additional per-priority GP penalties for missed P1/P2
    missed = [t for t in eligible if not t.completed]
    for t in missed:
        p = _prio(t)
        gp_penalty += PRIORITY_GP_PENALTY.get(p, 0)

    # Recidivism
    recidive = await _get_recidive_count(session, user.id, today)
    mult = RECIDIVE_MULT.get(recidive, RECIDIVE_CAP if recidive >= 5 else 1.0)
    xp_pct = min(DAILY_XP_PCT_CAP, xp_pct * mult)
    gp_penalty = min(DAILY_GP_CAP, int(gp_penalty * mult))

    # Garmin reduction (Body Battery < 20 or Sleep Score < 40)
    garmin_reduction = await _check_garmin_reduction(session, user.id, today)
    if garmin_reduction:
        xp_pct *= 0.5
        gp_penalty = int(gp_penalty * 0.5)

    # Redemption: yesterday was a penalty day but today is 100%
    redemption = False
    if status == CompletionStatus.PERFECT:
        yesterday_rec = await _get_yesterday_penalty(session, user.id, today)
        if yesterday_rec and yesterday_rec.status != CompletionStatus.PERFECT:
            redemption = True
            user.profile.xp += 30
            session.add(user.profile)
            await publish(topics.RPG_EVENTS, topics.REDEMPTION_BONUS, {
                "discord_id": user.discord_id,
                "date": str(today),
            })

    rec = PenaltyRecord(
        user_id=user.id,
        record_date=today,
        weighted_completion_pct=pct,
        status=status,
        xp_penalty_pct=xp_pct,
        gp_penalty=gp_penalty,
        recidive_day=recidive,
        recidive_multiplier=mult,
        garmin_reduction=garmin_reduction,
        redemption_next_day=redemption,
    )
    session.add(rec)

    # Apply GP penalty immediately to profile
    if gp_penalty > 0:
        user.profile.gp = max(0, user.profile.gp - gp_penalty)
        session.add(user.profile)

    # Streak resets
    if status in (CompletionStatus.INSUFFICIENT, CompletionStatus.CRITICAL, CompletionStatus.ABANDONED):
        await reset_streak(session, user, "daily")

    # Skill penalty for CRITICAL
    if status == CompletionStatus.CRITICAL:
        await _apply_skill_penalty(session, user, 2)

    # Willpower level −1 for ABANDONED
    if status == CompletionStatus.ABANDONED:
        user.profile.willpower_level = max(1, user.profile.willpower_level - 1)
        session.add(user.profile)

    # Publish events
    if xp_pct > 0:
        await publish(topics.PENALTIES_EVENTS, topics.PENALTY_APPLIED, {
            "discord_id": user.discord_id,
            "date": str(today),
            "xp_pct": xp_pct,
            "gp": gp_penalty,
            "status": status.value,
        })
    elif status == CompletionStatus.NEAR_COMPLETE:
        await publish(topics.PENALTIES_EVENTS, topics.SOFT_WARNING_SENT, {
            "discord_id": user.discord_id,
            "date": str(today),
        })

    # Recidivism escalation
    if pct < 50:
        new_recidive = recidive + 1
        await _set_recidive_count(session, user, new_recidive, today)
        if new_recidive >= 2:
            await publish(topics.PENALTIES_EVENTS, topics.RECIDIVE_INCREMENTED, {
                "discord_id": user.discord_id,
                "day": new_recidive,
            })
        if new_recidive >= 5:
            await publish(topics.PENALTIES_EVENTS, topics.RECOVERY_CHALLENGE_SENT, {
                "discord_id": user.discord_id,
            })
    elif status == CompletionStatus.PERFECT:
        await _reset_recidive(session, user, today)
        await publish(topics.PENALTIES_EVENTS, topics.RECIDIVE_RESET, {"discord_id": user.discord_id})

    return rec


# ── Helpers ───────────────────────────────────────────────────────────────────

async def _is_grace_day(session: AsyncSession, user_id: int, today: date) -> bool:
    result = await session.execute(
        select(GraceDay).where(GraceDay.user_id == user_id, GraceDay.used_on == today)
    )
    return result.scalar_one_or_none() is not None


async def _is_on_vacation(session: AsyncSession, user_id: int, today: date) -> bool:
    result = await session.execute(
        select(VacationMode).where(
            VacationMode.user_id == user_id,
            VacationMode.start_date <= today,
            VacationMode.end_date >= today,
        )
    )
    return result.scalar_one_or_none() is not None


async def _get_recidive_count(session: AsyncSession, user_id: int, today: date) -> int:
    yesterday = today - timedelta(days=1)
    result = await session.execute(
        select(PenaltyRecord).where(
            PenaltyRecord.user_id == user_id,
            PenaltyRecord.record_date == yesterday,
        )
    )
    rec = result.scalar_one_or_none()
    if rec and rec.weighted_completion_pct < 50:
        return rec.recidive_day + 1
    return 1  # day 1 baseline


async def _set_recidive_count(session: AsyncSession, user: User, count: int, today: date) -> None:
    result = await session.execute(
        select(PenaltyRecord).where(
            PenaltyRecord.user_id == user.id,
            PenaltyRecord.record_date == today,
        )
    )
    rec = result.scalar_one_or_none()
    if rec:
        rec.recidive_day = count
        session.add(rec)


async def _reset_recidive(session: AsyncSession, user: User, today: date) -> None:
    result = await session.execute(
        select(PenaltyRecord).where(
            PenaltyRecord.user_id == user.id,
            PenaltyRecord.record_date == today,
        )
    )
    rec = result.scalar_one_or_none()
    if rec:
        rec.recidive_day = 0
        rec.recidive_multiplier = 1.0
        session.add(rec)


async def _get_yesterday_penalty(
    session: AsyncSession, user_id: int, today: date
) -> PenaltyRecord | None:
    yesterday = today - timedelta(days=1)
    result = await session.execute(
        select(PenaltyRecord).where(
            PenaltyRecord.user_id == user_id,
            PenaltyRecord.record_date == yesterday,
        )
    )
    return result.scalar_one_or_none()


async def _check_garmin_reduction(session: AsyncSession, user_id: int, today: date) -> bool:
    result = await session.execute(
        select(SleepLog).where(SleepLog.user_id == user_id, SleepLog.sleep_date == today)
    )
    log = result.scalar_one_or_none()
    if log and (log.body_battery < 20 or log.sleep_score < 40):
        return True
    return False


async def _apply_skill_penalty(session: AsyncSession, user: User, points: int) -> None:
    from bot.database.models import UserSkill
    result = await session.execute(
        select(UserSkill).where(UserSkill.user_id == user.id)
    )
    skills = result.scalars().all()
    for skill in skills:
        skill.points = max(0, skill.points - points)
        session.add(skill)
