"""§2.3 — Productivity cog: Todoist integration, shared to-do list."""
from __future__ import annotations

import logging
from datetime import date

import discord
from discord import app_commands
from discord.ext import commands
from sqlalchemy import select

from bot.database.connection import get_session
from bot.database.models import DailyLog, TaskPriority, TaskTag, User
from bot.services.todoist import TodoistClient, parse_priority, parse_tag
from bot.services.encryption import decrypt, encrypt
from bot.utils.embeds import PRIORITY_EMOJI, TAG_EMOJI

logger = logging.getLogger(__name__)


class ProductivityCog(commands.Cog, name="Productivity"):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(name="connect-todoist", description="Connecte ton compte Todoist avec ta clé API")
    @app_commands.describe(api_key="Ta clé API Todoist (Paramètres → Intégrations → Clé API)")
    async def connect_todoist(self, interaction: discord.Interaction, api_key: str) -> None:
        await interaction.response.defer(ephemeral=True)
        client = TodoistClient(api_key)
        try:
            todoist_user = await client.get_current_user()
        except Exception:
            await interaction.followup.send(
                "Clé API invalide. Vérifie ta clé sur todoist.com → Paramètres → Intégrations.",
                ephemeral=True,
            )
            return

        todoist_user_id = str(todoist_user.get("id", ""))
        async with get_session() as session:
            user_result = await session.execute(
                select(User).where(User.discord_id == interaction.user.id)
            )
            user = user_result.scalar_one_or_none()
            if not user:
                await interaction.followup.send("Profil introuvable. Utilise `/register` d'abord.", ephemeral=True)
                return

            user.todoist_access_token = encrypt(api_key)
            user.todoist_user_id = todoist_user_id
            session.add(user)

        name = todoist_user.get("full_name") or todoist_user.get("email", "")
        embed = discord.Embed(
            title="✅ Todoist connecté",
            description=f"Compte **{name}** lié avec succès.\nUtilise `/sync-todoist` pour importer tes tâches.",
            color=discord.Color.green(),
        )
        await interaction.followup.send(embed=embed, ephemeral=True)

    @app_commands.command(name="sync-todoist", description="Synchronise tes tâches Todoist du jour")
    async def sync_todoist(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True)
        async with get_session() as session:
            user_result = await session.execute(
                select(User).where(User.discord_id == interaction.user.id)
            )
            user = user_result.scalar_one_or_none()
            if not user or not user.todoist_access_token:
                await interaction.followup.send(
                    "Ton compte Todoist n'est pas connecté. Connecte-le via le tableau de bord.",
                    ephemeral=True,
                )
                return

            token = decrypt(user.todoist_access_token)
            client = TodoistClient(token)
            try:
                tasks = await client.get_tasks_due_today()
            except Exception as e:
                logger.exception("Todoist sync failed for user %s", user.discord_id)
                await interaction.followup.send(f"Erreur Todoist : {e}", ephemeral=True)
                return

            today = date.today()
            synced = 0
            for task in tasks:
                task_id = str(task["id"])
                existing = await session.execute(
                    select(DailyLog).where(
                        DailyLog.user_id == user.id,
                        DailyLog.todoist_task_id == task_id,
                        DailyLog.log_date == today,
                    )
                )
                if existing.scalar_one_or_none():
                    continue

                labels: list[str] = task.get("labels", [])
                tag_str = parse_tag(labels)
                prio_str = parse_priority(task.get("priority", 1))
                is_recurring = bool(task.get("due", {}).get("is_recurring", False))

                log = DailyLog(
                    user_id=user.id,
                    log_date=today,
                    todoist_task_id=task_id,
                    task_name=task.get("content", ""),
                    tag=TaskTag(tag_str),
                    priority=TaskPriority(prio_str),
                    is_recurring=is_recurring,
                    completed=task.get("is_completed", False),
                )
                session.add(log)
                synced += 1

        embed = discord.Embed(
            title="🔄 Synchronisation Todoist",
            description=f"**{synced}** nouvelle(s) tâche(s) importée(s) pour aujourd'hui.",
            color=discord.Color.green(),
        )
        await interaction.followup.send(embed=embed, ephemeral=True)

    @app_commands.command(name="taches", description="Liste tes tâches Todoist du jour")
    async def list_tasks(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True)
        today = date.today()
        async with get_session() as session:
            user_result = await session.execute(
                select(User).where(User.discord_id == interaction.user.id)
            )
            user = user_result.scalar_one_or_none()
            if not user:
                await interaction.followup.send("Profil introuvable.", ephemeral=True)
                return

            result = await session.execute(
                select(DailyLog).where(
                    DailyLog.user_id == user.id,
                    DailyLog.log_date == today,
                ).order_by(DailyLog.priority)
            )
            tasks = result.scalars().all()

        if not tasks:
            await interaction.followup.send("Aucune tâche pour aujourd'hui. Utilise `/sync-todoist`.", ephemeral=True)
            return

        lines = []
        for t in tasks:
            status = "✅" if t.completed else "⏳"
            prio = t.priority.value if isinstance(t.priority, TaskPriority) else t.priority
            tag = t.tag.value if isinstance(t.tag, TaskTag) else t.tag
            lines.append(
                f"{status} {PRIORITY_EMOJI.get(prio, '▪')} {TAG_EMOJI.get(tag, '▪')} **{t.task_name}**"
            )

        embed = discord.Embed(
            title=f"📋 Tâches du {today}",
            description="\n".join(lines),
            color=discord.Color.blurple(),
        )
        done = sum(1 for t in tasks if t.completed)
        embed.set_footer(text=f"{done}/{len(tasks)} complétées")
        await interaction.followup.send(embed=embed, ephemeral=True)

    @app_commands.command(name="historique", description="Dernières tâches complétées avec XP/GP")
    @app_commands.describe(n="Nombre de tâches à afficher (défaut : 10)")
    async def history(self, interaction: discord.Interaction, n: int = 10) -> None:
        await interaction.response.defer(ephemeral=True)
        n = min(n, 25)
        async with get_session() as session:
            user_result = await session.execute(
                select(User).where(User.discord_id == interaction.user.id)
            )
            user = user_result.scalar_one_or_none()
            if not user:
                await interaction.followup.send("Profil introuvable.", ephemeral=True)
                return

            result = await session.execute(
                select(DailyLog)
                .where(DailyLog.user_id == user.id, DailyLog.completed == True)  # noqa: E712
                .order_by(DailyLog.completed_at.desc())
                .limit(n)
            )
            logs = result.scalars().all()

        if not logs:
            await interaction.followup.send("Aucune tâche complétée.", ephemeral=True)
            return

        lines = []
        for log in logs:
            prio = log.priority.value if isinstance(log.priority, TaskPriority) else log.priority
            lines.append(
                f"{PRIORITY_EMOJI.get(prio, '▪')} **{log.task_name}** — "
                f"+{log.xp_earned} XP | +{log.gp_earned} GP | {log.log_date}"
            )

        embed = discord.Embed(
            title=f"📜 Historique ({n} dernières)",
            description="\n".join(lines),
            color=discord.Color.blurple(),
        )
        await interaction.followup.send(embed=embed, ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(ProductivityCog(bot))
