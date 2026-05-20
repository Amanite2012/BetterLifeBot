"""§2.6 — Garmin sleep tracking cog."""
from __future__ import annotations

import logging
from datetime import date, timedelta

import discord
from discord import app_commands
from discord.ext import commands
from sqlalchemy import select

from bot.database.connection import get_session
from bot.database.models import GarminToken, SleepLog, User
from bot.services.garmin import build_oauth_url
from bot.utils.embeds import build_sleep_embed, COLOR_INFO, COLOR_SUCCESS

logger = logging.getLogger(__name__)


class GarminCog(commands.Cog, name="Garmin"):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(name="garmin-connect", description="Connecte ta montre Garmin via OAuth 2.0")
    async def garmin_connect(self, interaction: discord.Interaction) -> None:
        url = build_oauth_url()
        embed = discord.Embed(
            title="⌚ Connexion Garmin Health",
            description=(
                f"[Clique ici pour autoriser BetterLifeBot]({url})\n\n"
                "Tes données de sommeil et Body Battery seront synchronisées chaque matin à 06h00.\n"
                "_Tokens chiffrés AES-256. Jamais exposés dans les logs._"
            ),
            color=discord.Color.blurple(),
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="garmin-status", description="État de la connexion Garmin")
    async def garmin_status(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True)
        async with get_session() as session:
            user_result = await session.execute(
                select(User).where(User.discord_id == interaction.user.id)
            )
            user = user_result.scalar_one_or_none()
            if not user:
                await interaction.followup.send("Profil introuvable.", ephemeral=True)
                return

            token_result = await session.execute(
                select(GarminToken).where(GarminToken.user_id == user.id)
            )
            token = token_result.scalar_one_or_none()

        if not token:
            embed = discord.Embed(
                title="⌚ Garmin — Non connecté",
                description="Utilise `/garmin-connect` pour lier ta montre.",
                color=discord.Color.red(),
            )
        else:
            last = token.last_sync.strftime("%d/%m/%Y %H:%M") if token.last_sync else "Jamais"
            embed = discord.Embed(
                title="⌚ Garmin — Connecté ✅",
                description=f"Dernière synchronisation : **{last}**",
                color=COLOR_SUCCESS,
            )
        await interaction.followup.send(embed=embed, ephemeral=True)

    @app_commands.command(name="garmin-disconnect", description="Déconnecte ta montre Garmin")
    async def garmin_disconnect(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True)
        async with get_session() as session:
            user_result = await session.execute(
                select(User).where(User.discord_id == interaction.user.id)
            )
            user = user_result.scalar_one_or_none()
            if not user:
                await interaction.followup.send("Profil introuvable.", ephemeral=True)
                return

            token_result = await session.execute(
                select(GarminToken).where(GarminToken.user_id == user.id)
            )
            token = token_result.scalar_one_or_none()
            if token:
                await session.delete(token)

        await interaction.followup.send(
            "✅ Garmin déconnecté. Tes tokens ont été révoqués et tes données personnelles supprimées.",
            ephemeral=True,
        )

    @app_commands.command(name="sommeil-aujourd-hui", description="Résumé de ta nuit précédente")
    async def sleep_today(self, interaction: discord.Interaction) -> None:
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
                select(SleepLog).where(SleepLog.user_id == user.id, SleepLog.sleep_date == today)
            )
            log = result.scalar_one_or_none()

        if not log:
            await interaction.followup.send(
                "Aucune donnée de sommeil pour aujourd'hui. Garmin synchronise à 06h00.",
                ephemeral=True,
            )
            return

        embed = build_sleep_embed(log)
        await interaction.followup.send(embed=embed, ephemeral=True)

    @app_commands.command(name="sommeil-semaine", description="Rapport hebdomadaire de sommeil")
    async def sleep_week(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True)
        today = date.today()
        week_ago = today - timedelta(days=7)

        async with get_session() as session:
            user_result = await session.execute(
                select(User).where(User.discord_id == interaction.user.id)
            )
            user = user_result.scalar_one_or_none()
            if not user:
                await interaction.followup.send("Profil introuvable.", ephemeral=True)
                return

            result = await session.execute(
                select(SleepLog)
                .where(SleepLog.user_id == user.id, SleepLog.sleep_date >= week_ago)
                .order_by(SleepLog.sleep_date.desc())
            )
            logs = result.scalars().all()

        if not logs:
            await interaction.followup.send("Aucune donnée de sommeil cette semaine.", ephemeral=True)
            return

        avg_score = sum(l.sleep_score for l in logs) / len(logs)
        avg_duration = sum(l.duration_minutes for l in logs) / len(logs)
        avg_battery = sum(l.body_battery for l in logs) / len(logs)

        embed = discord.Embed(
            title="📊 Rapport Sommeil — 7 derniers jours",
            color=COLOR_INFO,
        )
        embed.add_field(name="Score moyen", value=f"{avg_score:.0f}/100", inline=True)
        embed.add_field(name="Durée moyenne", value=f"{avg_duration / 60:.1f}h", inline=True)
        embed.add_field(name="Body Battery moyen", value=f"{avg_battery:.0f}/100", inline=True)

        lines = []
        for log in logs:
            h, m = divmod(log.duration_minutes, 60)
            lines.append(f"**{log.sleep_date}** — {log.sleep_score}/100 — {h}h{m:02d}")
        embed.add_field(name="Détail", value="\n".join(lines), inline=False)

        await interaction.followup.send(embed=embed, ephemeral=True)

    @app_commands.command(name="sommeil-objectif", description="Définit ton objectif de durée de sommeil")
    @app_commands.describe(heures="Durée cible en heures (défaut : 8)")
    async def sleep_goal(self, interaction: discord.Interaction, heures: float = 8.0) -> None:
        await interaction.response.defer(ephemeral=True)
        if not (4.0 <= heures <= 12.0):
            await interaction.followup.send("L'objectif doit être entre 4 et 12 heures.", ephemeral=True)
            return
        async with get_session() as session:
            user_result = await session.execute(
                select(User).where(User.discord_id == interaction.user.id)
            )
            user = user_result.scalar_one_or_none()
            if not user:
                await interaction.followup.send("Profil introuvable.", ephemeral=True)
                return
            user.sleep_goal_hours = heures
            session.add(user)

        await interaction.followup.send(
            f"✅ Objectif de sommeil mis à jour : **{heures}h**",
            ephemeral=True,
        )

    @app_commands.command(name="batterie", description="Affiche ton Body Battery actuel")
    async def battery(self, interaction: discord.Interaction) -> None:
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
                select(SleepLog).where(SleepLog.user_id == user.id, SleepLog.sleep_date == today)
            )
            log = result.scalar_one_or_none()

        if not log:
            await interaction.followup.send("Données Body Battery non disponibles aujourd'hui.", ephemeral=True)
            return

        color = discord.Color.green() if log.body_battery >= 50 else discord.Color.orange() if log.body_battery >= 20 else discord.Color.red()
        embed = discord.Embed(
            title="🔋 Body Battery",
            description=f"**{log.body_battery}/100**",
            color=color,
        )
        if log.body_battery < 20:
            embed.add_field(name="⚠️ Attention", value="Battery critique — défis de volonté désactivés et malus réduits.", inline=False)

        await interaction.followup.send(embed=embed, ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(GarminCog(bot))
