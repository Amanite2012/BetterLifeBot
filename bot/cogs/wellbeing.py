"""§2.2 — Wellbeing cog: gratitude journal, willpower challenges."""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone

import discord
from discord import app_commands
from discord.ext import commands
from sqlalchemy import select

from bot.database.connection import get_session
from bot.database.models import GratitudeEntry, User, WillpowerChallenge
from bot.database.queries import get_user_by_discord_id, get_user_by_id
from bot.utils.embeds import COLOR_SUCCESS, COLOR_WARNING, COLOR_DANGER

logger = logging.getLogger(__name__)

MAX_WILLPOWER_LEVEL = 15
CHALLENGE_DURATION_MINUTES = 30


class ChallengeView(discord.ui.View):
    """View shown during an active willpower challenge."""

    def __init__(self, challenge_id: int, user_discord_id: int) -> None:
        super().__init__(timeout=CHALLENGE_DURATION_MINUTES * 60)
        self.challenge_id = challenge_id
        self.user_discord_id = user_discord_id

    @discord.ui.button(label="✅ Défi réussi !", style=discord.ButtonStyle.success)
    async def success(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if interaction.user.id != self.user_discord_id:
            await interaction.response.send_message("Ce n'est pas ton défi !", ephemeral=True)
            return
        await self._resolve(interaction, success=True)

    @discord.ui.button(label="❌ Abandonner", style=discord.ButtonStyle.danger)
    async def fail(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if interaction.user.id != self.user_discord_id:
            await interaction.response.send_message("Ce n'est pas ton défi !", ephemeral=True)
            return
        await self._resolve(interaction, success=False)

    async def _resolve(self, interaction: discord.Interaction, success: bool) -> None:
        async with get_session() as session:
            result = await session.execute(
                select(WillpowerChallenge).where(WillpowerChallenge.id == self.challenge_id)
            )
            challenge = result.scalar_one_or_none()
            if not challenge or challenge.completed is not None:
                await interaction.response.send_message("Défi déjà terminé.", ephemeral=True)
                return

            user = await get_user_by_id(session, challenge.user_id)
            if not user:
                return

            challenge.completed = success
            session.add(challenge)

            old_level = user.profile.willpower_level
            if success:
                user.profile.willpower_level = min(MAX_WILLPOWER_LEVEL, old_level + 1)
            else:
                user.profile.willpower_level = max(1, old_level - 1)
            session.add(user.profile)

        for child in self.children:
            child.disabled = True  # type: ignore[union-attr]

        msg = (
            f"🎯 Défi réussi ! Niveau volonté : **{user.profile.willpower_level}**"
            if success
            else f"💔 Défi échoué. Niveau volonté : **{user.profile.willpower_level}**"
        )
        embed = discord.Embed(
            description=msg,
            color=COLOR_SUCCESS if success else COLOR_DANGER,
        )
        await interaction.response.edit_message(embed=embed, view=self)

    async def on_timeout(self) -> None:
        async with get_session() as session:
            result = await session.execute(
                select(WillpowerChallenge).where(WillpowerChallenge.id == self.challenge_id)
            )
            challenge = result.scalar_one_or_none()
            if challenge and challenge.completed is None:
                challenge.completed = False
                user = await get_user_by_id(session, challenge.user_id)
                if user:
                    user.profile.willpower_level = max(1, user.profile.willpower_level - 1)
                    session.add(user.profile)
                session.add(challenge)


class WellbeingCog(commands.Cog, name="Wellbeing"):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(name="gratitude", description="Enregistre ta note de gratitude du jour (privée)")
    @app_commands.describe(note="Ta pensée positive du jour")
    async def gratitude(self, interaction: discord.Interaction, note: str) -> None:
        await interaction.response.defer(ephemeral=True)
        today = date.today()
        async with get_session() as session:
            user = await get_user_by_discord_id(session, interaction.user.id)
            if not user:
                await interaction.followup.send("Profil introuvable. Utilise `/register`.", ephemeral=True)
                return

            entry = GratitudeEntry(user_id=user.id, entry_date=today, content=note)
            session.add(entry)

        embed = discord.Embed(
            title="🙏 Gratitude enregistrée",
            description=f"_{note}_",
            color=COLOR_SUCCESS,
        )
        embed.set_footer(text="Cette note est strictement privée.")
        await interaction.followup.send(embed=embed, ephemeral=True)

    @app_commands.command(name="defi-volonte", description="Lance un défi de volonté (30 min max)")
    @app_commands.describe(description="Décris ton défi")
    async def willpower_challenge(self, interaction: discord.Interaction, description: str) -> None:
        await interaction.response.defer(ephemeral=False)
        async with get_session() as session:
            user = await get_user_by_discord_id(session, interaction.user.id)
            if not user:
                await interaction.followup.send("Profil introuvable.", ephemeral=True)
                return

            # Check Body Battery
            from bot.database.models import SleepLog
            sleep_result = await session.execute(
                select(SleepLog).where(
                    SleepLog.user_id == user.id,
                    SleepLog.sleep_date == date.today(),
                )
            )
            sleep = sleep_result.scalar_one_or_none()
            if sleep and sleep.body_battery < 20:
                await interaction.followup.send(
                    "⚠️ Ton Body Battery est inférieur à 20. Les défis de volonté sont temporairement désactivés. Repose-toi !",
                    ephemeral=True,
                )
                return

            now = datetime.now(timezone.utc)
            deadline = now + timedelta(minutes=CHALLENGE_DURATION_MINUTES)
            challenge = WillpowerChallenge(
                user_id=user.id,
                started_at=now,
                deadline_at=deadline,
                description=description,
                level_before=user.profile.willpower_level,
            )
            session.add(challenge)
            await session.flush()
            challenge_id = challenge.id

        embed = discord.Embed(
            title="⚡ Défi de Volonté lancé !",
            description=(
                f"**Défi :** {description}\n"
                f"⏱️ Tu as **{CHALLENGE_DURATION_MINUTES} minutes**.\n"
                f"Niveau volonté actuel : **{user.profile.willpower_level}/{MAX_WILLPOWER_LEVEL}**"
            ),
            color=COLOR_WARNING,
        )
        view = ChallengeView(challenge_id, interaction.user.id)
        await interaction.followup.send(embed=embed, view=view)

    @app_commands.command(name="gratitude-historique", description="Affiche tes dernières notes de gratitude")
    @app_commands.describe(n="Nombre d'entrées à afficher (défaut : 5)")
    async def gratitude_history(self, interaction: discord.Interaction, n: int = 5) -> None:
        await interaction.response.defer(ephemeral=True)
        n = min(n, 20)
        async with get_session() as session:
            user = await get_user_by_discord_id(session, interaction.user.id)
            if not user:
                await interaction.followup.send("Profil introuvable.", ephemeral=True)
                return

            result = await session.execute(
                select(GratitudeEntry)
                .where(GratitudeEntry.user_id == user.id)
                .order_by(GratitudeEntry.entry_date.desc())
                .limit(n)
            )
            entries = result.scalars().all()

        if not entries:
            await interaction.followup.send("Aucune note de gratitude enregistrée.", ephemeral=True)
            return

        embed = discord.Embed(title=f"🙏 Tes {n} dernières gratitudes", color=COLOR_SUCCESS)
        for e in entries:
            embed.add_field(name=str(e.entry_date), value=f"_{e.content}_", inline=False)
        await interaction.followup.send(embed=embed, ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(WellbeingCog(bot))
