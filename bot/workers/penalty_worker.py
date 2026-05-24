"""Penalty audit worker — cron at 23h55 local time per user."""
from __future__ import annotations

import logging
from datetime import date

from sqlalchemy import select

from bot.database.connection import get_session
from bot.database.models import User
from bot.database.queries import get_user_by_id
from bot.kafka import publish, topics
from bot.services.penalty import run_daily_audit
from bot.services.rpg import check_combo_bonus

logger = logging.getLogger(__name__)


async def run_audit_for_user(user: User) -> None:
    """Run the penalty audit for a single user."""
    today = date.today()
    async with get_session() as session:
        user = await get_user_by_id(session, user.id)
        if not user or not user.profile:
            return

        # Check combo bonus (3 different tags today)
        combo = await check_combo_bonus(session, user, today)
        if combo:
            logger.info("Combo bonus awarded to user %s", user.discord_id)

        # Run penalty audit
        record = await run_daily_audit(session, user, today)

    logger.info(
        "Penalty audit done for user %s: %.0f%% completion, status=%s",
        user.discord_id,
        record.weighted_completion_pct,
        record.status.value if hasattr(record.status, "value") else record.status,
    )

    await publish(topics.PENALTIES_EVENTS, topics.DAILY_AUDIT_TRIGGERED, {
        "discord_id": user.discord_id,
        "date": str(today),
        "completion_pct": record.weighted_completion_pct,
        "status": record.status.value if hasattr(record.status, "value") else str(record.status),
    })


async def run_all_audits() -> None:
    """Called by APScheduler at 23h55 UTC — iterates all users."""
    async with get_session() as session:
        result = await session.execute(select(User))
        users = result.scalars().all()

    logger.info("Starting penalty audit for %d user(s)", len(users))
    for user in users:
        try:
            await run_audit_for_user(user)
        except Exception:
            logger.exception("Penalty audit failed for user %s", getattr(user, "discord_id", "?"))
