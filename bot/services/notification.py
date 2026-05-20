"""Discord notification helpers — DM and channel messages."""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import discord

if TYPE_CHECKING:
    from bot.database.models import PenaltyRecord, User

logger = logging.getLogger(__name__)


async def dm_user(bot: discord.Client, discord_id: int, content: str | None = None, embed: discord.Embed | None = None) -> bool:
    try:
        user = await bot.fetch_user(discord_id)
        await user.send(content=content, embed=embed)
        return True
    except discord.Forbidden:
        logger.warning("Cannot DM user %s (DMs closed)", discord_id)
    except Exception:
        logger.exception("Failed to DM user %s", discord_id)
    return False


async def send_penalty_dm(bot: discord.Client, discord_id: int, record: "PenaltyRecord") -> None:
    from bot.utils.embeds import build_penalty_embed
    embed = build_penalty_embed(record)
    await dm_user(bot, discord_id, embed=embed)


async def send_sleep_alert(bot: discord.Client, discord_id: int, sleep_score: int) -> None:
    embed = discord.Embed(
        title="⚠️ Alerte Sommeil Critique",
        description=(
            f"Ton score de sommeil de la nuit est **{sleep_score}/100** (< 40).\n"
            "Tes malus du jour sont réduits de **50%** automatiquement.\n"
            "_Prends soin de toi — la récupération est essentielle._"
        ),
        color=discord.Color.red(),
    )
    await dm_user(bot, discord_id, embed=embed)
