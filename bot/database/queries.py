"""Reusable eager-loading User queries for SQLAlchemy async sessions.

SQLAlchemy async does NOT support implicit lazy loading. Every relationship
access must be covered by selectinload() at query time or via session.refresh().
Use these helpers instead of bare select(User) whenever you'll touch relations.
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from bot.database.models import User


def _user_full_options():
    """selectinload options that cover every relationship accessed in cogs/services."""
    return [
        selectinload(User.profile),
        selectinload(User.skills),
        selectinload(User.streaks),
        selectinload(User.garmin_token),
    ]


async def get_user_by_discord_id(session: AsyncSession, discord_id: int) -> User | None:
    result = await session.execute(
        select(User)
        .options(*_user_full_options())
        .where(User.discord_id == discord_id)
    )
    return result.scalar_one_or_none()


async def get_user_by_id(session: AsyncSession, user_id: int) -> User | None:
    result = await session.execute(
        select(User)
        .options(*_user_full_options())
        .where(User.id == user_id)
    )
    return result.scalar_one_or_none()


async def get_user_by_todoist_id(session: AsyncSession, todoist_user_id: str) -> User | None:
    result = await session.execute(
        select(User)
        .options(*_user_full_options())
        .where(User.todoist_user_id == todoist_user_id)
    )
    return result.scalar_one_or_none()
