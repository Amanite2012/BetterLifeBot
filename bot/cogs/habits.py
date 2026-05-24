"""§2.1 — Habit Tracker cog: morning task display, one-click validation, streaks."""
from __future__ import annotations

import logging
from datetime import date, datetime, timezone

import discord
from discord import app_commands
from discord.ext import commands
from sqlalchemy import select

from bot.database.connection import get_session
from bot.database.models import DailyLog, HabitStreak, TaskPriority, TaskTag, User
from bot.database.queries import get_user_by_discord_id, get_user_by_id
from bot.services.rpg import apply_task_completion
from bot.services.streak import record_completion
from bot.utils.embeds import TAG_EMOJI, PRIORITY_EMOJI, COLOR_SUCCESS, COLOR_WARNING

logger = logging.getLogger(__name__)


class HabitValidationView(discord.ui.View):
    """Persistent view with Validé / Non réalisé buttons for a single habit task."""

    def __init__(self, log_id: int, user_discord_id: int) -> None:
        super().__init__(timeout=None)
        self.log_id = log_id
        self.user_discord_id = user_discord_id

    @discord.ui.button(label="✅ Validé", style=discord.ButtonStyle.success, custom_id="habit_done")
    async def done(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if interaction.user.id != self.user_discord_id:
            await interaction.response.send_message("Ce n'est pas ta tâche !", ephemeral=True)
            return
        await self._handle(interaction, completed=True)

    @discord.ui.button(label="❌ Non réalisé", style=discord.ButtonStyle.danger, custom_id="habit_skip")
    async def skip(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if interaction.user.id != self.user_discord_id:
            await interaction.response.send_message("Ce n'est pas ta tâche !", ephemeral=True)
            return
        await self._handle(interaction, completed=False)

    async def _handle(self, interaction: discord.Interaction, completed: bool) -> None:
        async with get_session() as session:
            result = await session.execute(select(DailyLog).where(DailyLog.id == self.log_id))
            log = result.scalar_one_or_none()
            if not log:
                await interaction.response.send_message("Tâche introuvable.", ephemeral=True)
                return
            if log.completed:
                await interaction.response.send_message("Déjà validée !", ephemeral=True)
                return

            user = await get_user_by_id(session, log.user_id)
            if not user or not user.profile:
                await interaction.response.send_message("Profil introuvable.", ephemeral=True)
                return

            log.completed = completed
            log.completed_at = datetime.now(timezone.utc) if completed else None
            session.add(log)

            xp_msg = ""
            if completed:
                xp, gp, levelled_up, skilled_up = await apply_task_completion(session, user, log)
                await record_completion(session, user, date.today(), "daily")
                tag_emoji = TAG_EMOJI.get(log.tag.value if hasattr(log.tag, "value") else str(log.tag), "▪")
                xp_msg = f"\n+**{xp} XP** | +**{gp} GP** {tag_emoji}"
                if levelled_up:
                    xp_msg += f"\n🎉 **Level Up!** Niveau {user.profile.level}"

        for child in self.children:
            child.disabled = True  # type: ignore[union-attr]

        embed = discord.Embed(
            title="✅ Tâche validée !" if completed else "❌ Tâche non réalisée",
            description=f"**{log.task_name}**{xp_msg}",
            color=COLOR_SUCCESS if completed else COLOR_WARNING,
        )
        await interaction.response.edit_message(embed=embed, view=self)


class HabitsCog(commands.Cog, name="Habits"):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    async def send_morning_habits(self, user: User, channel: discord.TextChannel) -> None:
        """Called by the scheduler at the user's local morning time."""
        today = date.today()
        async with get_session() as session:
            result = await session.execute(
                select(DailyLog).where(
                    DailyLog.user_id == user.id,
                    DailyLog.log_date == today,
                    DailyLog.completed == False,  # noqa: E712
                )
            )
            tasks = result.scalars().all()

        if not tasks:
            return

        for log in tasks:
            prio = log.priority.value if isinstance(log.priority, TaskPriority) else log.priority
            tag = log.tag.value if isinstance(log.tag, TaskTag) else log.tag
            embed = discord.Embed(
                title=f"{PRIORITY_EMOJI.get(prio, '▪')} {log.task_name}",
                description=(
                    f"Priorité : **{prio}** | Catégorie : {TAG_EMOJI.get(tag, '▪')} **{tag}**\n"
                    f"Valide ta tâche du jour !"
                ),
                color=discord.Color.blurple(),
            )
            view = HabitValidationView(log.id, user.discord_id)
            await channel.send(content=f"<@{user.discord_id}>", embed=embed, view=view)

    # ── Slash commands ────────────────────────────────────────────────────────

    @app_commands.command(name="habitudes", description="Affiche tes habitudes du jour")
    async def show_habits(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True)
        today = date.today()
        async with get_session() as session:
            user = await get_user_by_discord_id(session, interaction.user.id)
            if not user:
                await interaction.followup.send("Ton profil est introuvable. Utilise `/register`.", ephemeral=True)
                return

            result = await session.execute(
                select(DailyLog).where(
                    DailyLog.user_id == user.id,
                    DailyLog.log_date == today,
                )
            )
            tasks = result.scalars().all()

        if not tasks:
            await interaction.followup.send("Aucune tâche pour aujourd'hui.", ephemeral=True)
            return

        lines = []
        for t in tasks:
            status = "✅" if t.completed else "⏳"
            prio = t.priority.value if isinstance(t.priority, TaskPriority) else t.priority
            lines.append(f"{status} {PRIORITY_EMOJI.get(prio, '▪')} **{t.task_name}**")

        embed = discord.Embed(
            title=f"📋 Habitudes du {today}",
            description="\n".join(lines),
            color=discord.Color.blurple(),
        )
        await interaction.followup.send(embed=embed, ephemeral=True)

    @app_commands.command(name="streak", description="Affiche ta série actuelle")
    async def show_streak(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True)
        async with get_session() as session:
            user = await get_user_by_discord_id(session, interaction.user.id)
            if not user:
                await interaction.followup.send("Profil introuvable.", ephemeral=True)
                return

            result = await session.execute(
                select(HabitStreak).where(HabitStreak.user_id == user.id)
            )
            streaks = result.scalars().all()

        if not streaks:
            await interaction.followup.send("Aucune série enregistrée.", ephemeral=True)
            return

        embed = discord.Embed(title="🔥 Tes Séries", color=discord.Color.orange())
        for s in streaks:
            embed.add_field(
                name=s.streak_type.capitalize(),
                value=f"Actuelle : **{s.current_streak}** | Record : **{s.longest_streak}**",
                inline=False,
            )
        await interaction.followup.send(embed=embed, ephemeral=True)

    @app_commands.command(name="register", description="Crée ton profil BetterLifeBot")
    @app_commands.describe(timezone="Ton fuseau horaire (ex: Europe/Paris)")
    async def register(self, interaction: discord.Interaction, timezone: str = "Europe/Paris") -> None:
        await interaction.response.defer(ephemeral=True)
        async with get_session() as session:
            existing = await get_user_by_discord_id(session, interaction.user.id)
            if existing:
                await interaction.followup.send("Tu as déjà un profil !", ephemeral=True)
                return

            from bot.database.models import UserProfile
            from bot.config import get_settings
            user = User(
                discord_id=interaction.user.id,
                timezone=timezone,
                sleep_goal_hours=get_settings().default_sleep_goal_hours,
            )
            session.add(user)
            await session.flush()
            profile = UserProfile(user_id=user.id)
            session.add(profile)

        await interaction.followup.send(
            "🎉 Bienvenue dans BetterLifeBot ! Ton profil RPG a été créé. Utilise `/profil` pour le voir.",
            ephemeral=True,
        )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(HabitsCog(bot))
