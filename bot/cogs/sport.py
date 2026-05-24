"""§2.4 — Sport cog: run scheduling via Google Calendar + OpenWeather."""
from __future__ import annotations

import logging
from datetime import datetime, timezone

import discord
from discord import app_commands
from discord.ext import commands
from sqlalchemy import select

from bot.database.connection import get_session
from bot.database.models import User
from bot.database.queries import get_user_by_discord_id
from bot.services import calendar as cal_service
from bot.services import weather as weather_service
from bot.services.encryption import decrypt

logger = logging.getLogger(__name__)


class SportCog(commands.Cog, name="Sport"):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(name="planifier-course", description="Trouve les meilleurs créneaux pour courir aujourd'hui")
    @app_commands.describe(
        lat="Latitude de ta position (ex: 48.8566)",
        lon="Longitude de ta position (ex: 2.3522)",
    )
    async def plan_run(self, interaction: discord.Interaction, lat: float, lon: float) -> None:
        await interaction.response.defer(ephemeral=True)

        async with get_session() as session:
            user = await get_user_by_discord_id(session, interaction.user.id)
            if not user:
                await interaction.followup.send("Profil introuvable.", ephemeral=True)
                return

            if not user.google_access_token:
                await interaction.followup.send(
                    "Ton Google Calendar n'est pas connecté. Utilise `/google-connect`.",
                    ephemeral=True,
                )
                return

            access_token = decrypt(user.google_access_token)

        try:
            now = datetime.now(timezone.utc)
            free_slots = await cal_service.get_free_slots(access_token, now, slot_duration_minutes=60)
            forecast = await weather_service.get_forecast(lat, lon)
            best = weather_service.best_running_slots(forecast, free_slots)
        except Exception as e:
            logger.exception("Sport planning failed for user %s", interaction.user.id)
            await interaction.followup.send(f"Erreur lors de la planification : {e}", ephemeral=True)
            return

        if not best:
            embed = discord.Embed(
                title="🏃 Planification de course",
                description="Aucun créneau optimal trouvé aujourd'hui (météo ou agenda chargé).",
                color=discord.Color.orange(),
            )
        else:
            embed = discord.Embed(
                title="🏃 Meilleurs créneaux pour courir",
                color=discord.Color.green(),
            )
            for slot in best[:5]:
                s = slot["start"]
                e = slot["end"]
                embed.add_field(
                    name=f"🕐 {s.strftime('%H:%M')} – {e.strftime('%H:%M')}",
                    value=(
                        f"🌡️ {slot['temp']:.1f}°C | 💨 {slot['wind']:.1f} m/s\n"
                        f"☁️ {slot['description']}"
                    ),
                    inline=False,
                )

        await interaction.followup.send(embed=embed, ephemeral=True)

    @app_commands.command(name="google-connect", description="Connecte ton Google Calendar")
    async def google_connect(self, interaction: discord.Interaction) -> None:
        import secrets
        state = secrets.token_urlsafe(16)
        url = cal_service.build_auth_url(state)
        embed = discord.Embed(
            title="📅 Connexion Google Calendar",
            description=f"[Clique ici pour autoriser l'accès]({url})\n\nAprès autorisation, ton agenda sera utilisé pour trouver tes créneaux de course.",
            color=discord.Color.blurple(),
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(SportCog(bot))
