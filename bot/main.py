"""BetterLifeBot — main entry point."""
from __future__ import annotations

import asyncio
import logging
import signal
import sys

import discord
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from discord.ext import commands

from bot.config import get_settings
from bot.database.connection import close_db, init_db
from bot.kafka.consumers import start_all_consumers
from bot.kafka.producer import close_producer
from bot.workers.garmin_sync import run_all_garmin_syncs
from bot.workers.penalty_worker import run_all_audits

# ── Logging ───────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger(__name__)

# ── Bot setup ─────────────────────────────────────────────────────────────────
intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents, help_command=None)
scheduler = AsyncIOScheduler()

COGS = [
    "bot.cogs.habits",
    "bot.cogs.wellbeing",
    "bot.cogs.productivity",
    "bot.cogs.sport",
    "bot.cogs.rpg",
    "bot.cogs.garmin",
    "bot.cogs.penalties",
]


@bot.event
async def on_ready() -> None:
    logger.info("Logged in as %s (ID: %s)", bot.user, bot.user.id)
    settings = get_settings()

    # Sync slash commands
    if settings.discord_guild_id:
        guild = discord.Object(id=settings.discord_guild_id)
        bot.tree.copy_global_to(guild=guild)
        await bot.tree.sync(guild=guild)
        logger.info("Slash commands synced to guild %s", settings.discord_guild_id)
    else:
        await bot.tree.sync()
        logger.info("Slash commands synced globally")

    # Start background services
    scheduler.start()
    asyncio.create_task(start_all_consumers())


@bot.event
async def on_error(event: str, *args, **kwargs) -> None:
    logger.exception("Unhandled error in event %s", event)


async def load_cogs() -> None:
    for cog in COGS:
        try:
            await bot.load_extension(cog)
            logger.info("Loaded cog: %s", cog)
        except Exception:
            logger.exception("Failed to load cog: %s", cog)


def setup_scheduler() -> None:
    """Register cron jobs."""
    # Garmin sync at 06h00 UTC daily
    scheduler.add_job(
        run_all_garmin_syncs,
        trigger="cron",
        hour=6,
        minute=0,
        id="garmin_sync",
        replace_existing=True,
    )
    # Penalty audit at 23h55 UTC daily
    scheduler.add_job(
        run_all_audits,
        trigger="cron",
        hour=23,
        minute=55,
        id="penalty_audit",
        replace_existing=True,
    )
    logger.info("Scheduler jobs registered")


async def main() -> None:
    settings = get_settings()

    # Init DB
    await init_db()
    logger.info("Database initialised")

    # Load cogs & scheduler
    await load_cogs()
    setup_scheduler()

    # Graceful shutdown
    loop = asyncio.get_running_loop()

    def _shutdown():
        logger.info("Shutdown signal received")
        loop.create_task(_cleanup())

    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, _shutdown)

    try:
        await bot.start(settings.discord_token)
    except KeyboardInterrupt:
        pass
    finally:
        await _cleanup()


async def _cleanup() -> None:
    logger.info("Cleaning up…")
    if scheduler.running:
        scheduler.shutdown(wait=False)
    await bot.close()
    await close_producer()
    await close_db()
    logger.info("Goodbye.")


if __name__ == "__main__":
    asyncio.run(main())
