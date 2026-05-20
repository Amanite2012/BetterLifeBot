"""§2.7 — Penalty system cog: /malus, /grace, /vacances, /récidive, /rattrapage."""
from __future__ import annotations

import logging
from datetime import date, timedelta

import discord
from discord import app_commands
from discord.ext import commands
from sqlalchemy import select, desc

from bot.database.connection import get_session
from bot.database.models import (
    GraceDay,
    PenaltyRecord,
    RecoveryChallenge,
    User,
    VacationMode,
)
from bot.utils.embeds import STATUS_EMOJI, build_penalty_embed, COLOR_INFO, COLOR_WARNING, COLOR_SUCCESS

logger = logging.getLogger(__name__)


class RecoveryChallengeView(discord.ui.View):
    """Shown when a recovery challenge is proposed."""

    def __init__(self, challenge_id: int, user_discord_id: int) -> None:
        super().__init__(timeout=7200)  # 2 hours
        self.challenge_id = challenge_id
        self.user_discord_id = user_discord_id

    @discord.ui.button(label="✅ Accepter le défi", style=discord.ButtonStyle.success)
    async def accept(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if interaction.user.id != self.user_discord_id:
            await interaction.response.send_message("Ce défi n'est pas pour toi !", ephemeral=True)
            return
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc)
        deadline = now + timedelta(hours=2)
        async with get_session() as session:
            result = await session.execute(
                select(RecoveryChallenge).where(RecoveryChallenge.id == self.challenge_id)
            )
            challenge = result.scalar_one_or_none()
            if not challenge or challenge.accepted_at:
                await interaction.response.send_message("Défi déjà accepté ou introuvable.", ephemeral=True)
                return
            challenge.accepted_at = now
            challenge.deadline_at = deadline
            session.add(challenge)

        embed = discord.Embed(
            title="⚔️ Défi de Rattrapage accepté !",
            description=(
                f"**Tâche :** {challenge.task_name}\n"
                f"⏱️ Deadline : {deadline.strftime('%H:%M')} (2 heures)\n"
                "Complète la tâche dans Todoist, puis utilise `/rattrapage-valider`."
            ),
            color=COLOR_WARNING,
        )
        for child in self.children:
            child.disabled = True  # type: ignore[union-attr]
        await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(label="❌ Refuser", style=discord.ButtonStyle.secondary)
    async def decline(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if interaction.user.id != self.user_discord_id:
            return
        for child in self.children:
            child.disabled = True  # type: ignore[union-attr]
        await interaction.response.edit_message(
            content="Défi refusé. Il sera reproposé demain si tu es encore en récidive.", view=self
        )


class PenaltiesCog(commands.Cog, name="Penalties"):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(name="malus-aujourd-hui", description="Récapitulatif des malus du jour")
    async def malus_today(self, interaction: discord.Interaction) -> None:
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
                select(PenaltyRecord).where(
                    PenaltyRecord.user_id == user.id,
                    PenaltyRecord.record_date == today,
                )
            )
            record = result.scalar_one_or_none()

        if not record:
            await interaction.followup.send(
                "Aucun bilan pour aujourd'hui (audit à 23h55).", ephemeral=True
            )
            return

        embed = build_penalty_embed(record)
        await interaction.followup.send(embed=embed, ephemeral=True)

    @app_commands.command(name="malus-historique", description="Historique des malus")
    @app_commands.describe(n="Nombre de jours (défaut : 7)")
    async def malus_history(self, interaction: discord.Interaction, n: int = 7) -> None:
        await interaction.response.defer(ephemeral=True)
        n = min(n, 30)
        async with get_session() as session:
            user_result = await session.execute(
                select(User).where(User.discord_id == interaction.user.id)
            )
            user = user_result.scalar_one_or_none()
            if not user:
                await interaction.followup.send("Profil introuvable.", ephemeral=True)
                return

            result = await session.execute(
                select(PenaltyRecord)
                .where(PenaltyRecord.user_id == user.id)
                .order_by(desc(PenaltyRecord.record_date))
                .limit(n)
            )
            records = result.scalars().all()

        if not records:
            await interaction.followup.send("Aucun historique de malus.", ephemeral=True)
            return

        embed = discord.Embed(title=f"📊 Historique malus — {n} derniers jours", color=COLOR_INFO)
        for rec in records:
            status = rec.status.value if hasattr(rec.status, "value") else rec.status
            emoji = STATUS_EMOJI.get(status, "❓")
            val = f"{rec.weighted_completion_pct:.0f}% | −{rec.xp_penalty_pct:.0f}% XP | −{rec.gp_penalty} GP"
            embed.add_field(name=f"{emoji} {rec.record_date}", value=val, inline=False)

        await interaction.followup.send(embed=embed, ephemeral=True)

    @app_commands.command(name="grace", description="Active ton jour de grâce mensuel (annule les malus du jour)")
    async def grace(self, interaction: discord.Interaction) -> None:
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

            # Check already used this month
            month_start = today.replace(day=1)
            used_result = await session.execute(
                select(GraceDay).where(
                    GraceDay.user_id == user.id,
                    GraceDay.used_on >= month_start,
                )
            )
            if used_result.scalar_one_or_none():
                await interaction.followup.send(
                    "Tu as déjà utilisé ton jour de grâce ce mois-ci.", ephemeral=True
                )
                return

            # Check already used today
            today_result = await session.execute(
                select(GraceDay).where(
                    GraceDay.user_id == user.id,
                    GraceDay.used_on == today,
                )
            )
            if today_result.scalar_one_or_none():
                await interaction.followup.send("Jour de grâce déjà activé aujourd'hui.", ephemeral=True)
                return

            grace = GraceDay(user_id=user.id, used_on=today)
            session.add(grace)

            # Remove today's penalty record if it exists
            pen_result = await session.execute(
                select(PenaltyRecord).where(
                    PenaltyRecord.user_id == user.id,
                    PenaltyRecord.record_date == today,
                )
            )
            pen = pen_result.scalar_one_or_none()
            if pen:
                pen.grace_day_used = True
                pen.xp_penalty_pct = 0.0
                pen.gp_penalty = 0
                session.add(pen)

        await interaction.followup.send(
            "🛡️ **Jour de grâce activé !** Aucun malus pour aujourd'hui. Prochain disponible le mois prochain.",
            ephemeral=True,
        )

    @app_commands.command(name="vacances", description="Active le mode vacances (suspend les malus)")
    @app_commands.describe(jours="Durée en jours (max 14, 1×/trimestre)")
    async def vacances(self, interaction: discord.Interaction, jours: int = 7) -> None:
        await interaction.response.defer(ephemeral=True)
        if not (1 <= jours <= 14):
            await interaction.followup.send("Durée entre 1 et 14 jours.", ephemeral=True)
            return

        today = date.today()
        quarter = (today.month - 1) // 3 + 1
        year = today.year

        async with get_session() as session:
            user_result = await session.execute(
                select(User).where(User.discord_id == interaction.user.id)
            )
            user = user_result.scalar_one_or_none()
            if not user:
                await interaction.followup.send("Profil introuvable.", ephemeral=True)
                return

            used_result = await session.execute(
                select(VacationMode).where(
                    VacationMode.user_id == user.id,
                    VacationMode.quarter_year == year * 10 + quarter,
                )
            )
            if used_result.scalar_one_or_none():
                await interaction.followup.send(
                    "Tu as déjà utilisé ton mode vacances ce trimestre.", ephemeral=True
                )
                return

            vac = VacationMode(
                user_id=user.id,
                start_date=today,
                end_date=today + timedelta(days=jours - 1),
                quarter_year=year * 10 + quarter,
            )
            session.add(vac)

        await interaction.followup.send(
            f"🏖️ **Mode vacances activé** pour **{jours} jours** jusqu'au {(today + timedelta(days=jours-1)).strftime('%d/%m/%Y')}.\n"
            "Les malus sont suspendus pendant cette période.",
            ephemeral=True,
        )

    @app_commands.command(name="recidive", description="Affiche ton compteur de récidive")
    async def recidive(self, interaction: discord.Interaction) -> None:
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
                select(PenaltyRecord).where(
                    PenaltyRecord.user_id == user.id,
                    PenaltyRecord.record_date == today,
                )
            )
            rec = result.scalar_one_or_none()

        day = rec.recidive_day if rec else 0
        mult = rec.recidive_multiplier if rec else 1.0

        embed = discord.Embed(
            title="🔁 Compteur de Récidive",
            description=f"Jour de récidive : **{day}**\nMultiplicateur malus : **×{mult}**",
            color=COLOR_WARNING if day > 0 else COLOR_SUCCESS,
        )
        if day >= 5:
            embed.add_field(name="🚨 Récidive critique", value="Un défi de rattrapage est disponible via `/rattrapage`.", inline=False)

        await interaction.followup.send(embed=embed, ephemeral=True)

    @app_commands.command(name="rattrapage", description="Lance un défi de rattrapage (récidive ≥ 5)")
    async def rattrapage(self, interaction: discord.Interaction) -> None:
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

            rec_result = await session.execute(
                select(PenaltyRecord).where(
                    PenaltyRecord.user_id == user.id,
                    PenaltyRecord.record_date == today,
                )
            )
            rec = rec_result.scalar_one_or_none()
            if not rec or rec.recidive_day < 5:
                await interaction.followup.send(
                    "Le défi de rattrapage n'est disponible qu'à partir du 5e jour de récidive.",
                    ephemeral=True,
                )
                return

            # Find most recent overdue P1/P2 task
            from bot.database.models import DailyLog, TaskPriority
            overdue_result = await session.execute(
                select(DailyLog).where(
                    DailyLog.user_id == user.id,
                    DailyLog.completed == False,  # noqa: E712
                    DailyLog.priority.in_([TaskPriority.P1, TaskPriority.P2]),
                ).order_by(desc(DailyLog.log_date)).limit(1)
            )
            task = overdue_result.scalar_one_or_none()
            if not task:
                await interaction.followup.send(
                    "Aucune tâche P1/P2 en retard trouvée.", ephemeral=True
                )
                return

            challenge = RecoveryChallenge(
                user_id=user.id,
                todoist_task_id=task.todoist_task_id,
                task_name=task.task_name,
            )
            session.add(challenge)
            await session.flush()
            challenge_id = challenge.id

        embed = discord.Embed(
            title="⚔️ Défi de Rattrapage disponible !",
            description=(
                f"**Tâche :** {task.task_name}\n"
                "⏱️ Délai : **2 heures** après acceptation\n"
                "✅ Réussite : Malus ÷2 + +50 XP Rédemption + récidive → 3"
            ),
            color=discord.Color.orange(),
        )
        view = RecoveryChallengeView(challenge_id, interaction.user.id)
        await interaction.followup.send(embed=embed, view=view, ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(PenaltiesCog(bot))
