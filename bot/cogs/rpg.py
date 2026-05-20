"""§2.5 — RPG system cog: /profil, /leaderboard, /shop, /historique, /bonus-actifs."""
from __future__ import annotations

import logging
from datetime import date

import discord
from discord import app_commands
from discord.ext import commands
from sqlalchemy import desc, select

from bot.database.connection import get_session
from bot.database.models import DailyLog, ShopItem, User, UserInventory, UserProfile
from bot.services.rpg import title_for_level, xp_required
from bot.utils.embeds import (
    COLOR_GOLD,
    COLOR_INFO,
    COLOR_SUCCESS,
    TAG_EMOJI,
    build_leaderboard_embed,
    build_profile_embed,
)

logger = logging.getLogger(__name__)


class ShopView(discord.ui.View):
    def __init__(self, items: list[ShopItem], user: User) -> None:
        super().__init__(timeout=120)
        self.items = items
        self.user = user
        for item in items[:5]:
            self.add_item(BuyButton(item, user))


class BuyButton(discord.ui.Button):
    def __init__(self, item: ShopItem, user: User) -> None:
        affordable = user.profile.gp >= item.cost_gp
        super().__init__(
            label=f"{item.name} ({item.cost_gp} GP)",
            style=discord.ButtonStyle.success if affordable else discord.ButtonStyle.secondary,
            disabled=not affordable,
        )
        self.item = item
        self.user = user

    async def callback(self, interaction: discord.Interaction) -> None:
        if interaction.user.id != self.user.discord_id:
            await interaction.response.send_message("Ce n'est pas ta boutique !", ephemeral=True)
            return
        async with get_session() as session:
            user_result = await session.execute(
                select(User).where(User.discord_id == interaction.user.id)
            )
            user = user_result.scalar_one_or_none()
            if not user or user.profile.gp < self.item.cost_gp:
                await interaction.response.send_message("GP insuffisants.", ephemeral=True)
                return

            user.profile.gp -= self.item.cost_gp
            inv = UserInventory(user_id=user.id, item_id=self.item.id)
            session.add(inv)
            session.add(user.profile)

        await interaction.response.send_message(
            f"✅ **{self.item.name}** acheté ! GP restants : {user.profile.gp}",
            ephemeral=True,
        )


class RPGCog(commands.Cog, name="RPG"):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(name="profil", description="Affiche le profil RPG")
    @app_commands.describe(user="Utilisateur à afficher (optionnel)")
    async def profil(self, interaction: discord.Interaction, user: discord.Member | None = None) -> None:
        await interaction.response.defer()
        target = user or interaction.user
        async with get_session() as session:
            result = await session.execute(
                select(User).where(User.discord_id == target.id)
            )
            db_user = result.scalar_one_or_none()
            if not db_user or not db_user.profile:
                await interaction.followup.send("Profil introuvable. Crée-en un avec `/register`.")
                return

            # Load relations
            await session.refresh(db_user, ["profile", "skills", "streaks"])

            # Fetch today's penalty
            from bot.database.models import PenaltyRecord
            penalty_result = await session.execute(
                select(PenaltyRecord).where(
                    PenaltyRecord.user_id == db_user.id,
                    PenaltyRecord.record_date == date.today(),
                )
            )
            today_penalty = penalty_result.scalar_one_or_none()

        embed = build_profile_embed(db_user)
        embed.set_author(name=target.display_name, icon_url=target.display_avatar.url)

        if today_penalty and today_penalty.xp_penalty_pct > 0:
            embed.add_field(
                name="⚠️ Malus actif",
                value=f"−{today_penalty.xp_penalty_pct:.0f}% XP demain",
                inline=True,
            )

        await interaction.followup.send(embed=embed)

    @app_commands.command(name="leaderboard", description="Classement global")
    @app_commands.describe(type="Type de classement : xp, gp, streak")
    @app_commands.choices(type=[
        app_commands.Choice(name="XP", value="xp"),
        app_commands.Choice(name="GP", value="gp"),
        app_commands.Choice(name="Streak", value="streak"),
    ])
    async def leaderboard(self, interaction: discord.Interaction, type: str = "xp") -> None:
        await interaction.response.defer()
        async with get_session() as session:
            if type == "xp":
                result = await session.execute(
                    select(User.discord_id, UserProfile.xp)
                    .join(UserProfile, UserProfile.user_id == User.id)
                    .order_by(desc(UserProfile.xp))
                    .limit(10)
                )
                entries = [{"discord_id": r[0], "value": f"{r[1]} XP"} for r in result.all()]
            elif type == "gp":
                result = await session.execute(
                    select(User.discord_id, UserProfile.gp)
                    .join(UserProfile, UserProfile.user_id == User.id)
                    .order_by(desc(UserProfile.gp))
                    .limit(10)
                )
                entries = [{"discord_id": r[0], "value": f"{r[1]} GP"} for r in result.all()]
            else:
                from bot.database.models import HabitStreak
                result = await session.execute(
                    select(User.discord_id, HabitStreak.current_streak)
                    .join(HabitStreak, HabitStreak.user_id == User.id)
                    .where(HabitStreak.streak_type == "daily")
                    .order_by(desc(HabitStreak.current_streak))
                    .limit(10)
                )
                entries = [{"discord_id": r[0], "value": f"{r[1]} jours"} for r in result.all()]

        embed = build_leaderboard_embed(entries, type)
        await interaction.followup.send(embed=embed)

    @app_commands.command(name="shop", description="Boutique — acheter des boosts avec tes GP")
    async def shop(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True)
        async with get_session() as session:
            user_result = await session.execute(
                select(User).where(User.discord_id == interaction.user.id)
            )
            user = user_result.scalar_one_or_none()
            if not user:
                await interaction.followup.send("Profil introuvable.", ephemeral=True)
                return
            await session.refresh(user, ["profile"])

            items_result = await session.execute(
                select(ShopItem).where(ShopItem.is_active == True)  # noqa: E712
            )
            items = items_result.scalars().all()

        if not items:
            await interaction.followup.send("La boutique est vide pour l'instant.", ephemeral=True)
            return

        embed = discord.Embed(
            title="🛒 Boutique BetterLifeBot",
            description=f"💰 Ton solde : **{user.profile.gp} GP**",
            color=COLOR_GOLD,
        )
        for item in items:
            embed.add_field(
                name=f"{item.name} — {item.cost_gp} GP",
                value=item.description,
                inline=False,
            )

        view = ShopView(items, user)
        await interaction.followup.send(embed=embed, view=view, ephemeral=True)

    @app_commands.command(name="bonus-actifs", description="Liste tes bonus passifs actifs")
    async def bonus_actifs(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True)
        async with get_session() as session:
            user_result = await session.execute(
                select(User).where(User.discord_id == interaction.user.id)
            )
            user = user_result.scalar_one_or_none()
            if not user:
                await interaction.followup.send("Profil introuvable.", ephemeral=True)
                return
            await session.refresh(user, ["profile", "skills"])

        lines = []
        profile = user.profile

        if profile.sleep_xp_modifier != 1.0:
            lines.append(f"🌙 Modificateur sommeil : ×{profile.sleep_xp_modifier:.1f} XP")
        if profile.xp_multiplier != 1.0 and profile.xp_multiplier_until:
            lines.append(
                f"⚡ Boost XP ×{profile.xp_multiplier:.1f} jusqu'à {profile.xp_multiplier_until.strftime('%H:%M')}"
            )
        if profile.gp_multiplier != 1.0:
            lines.append(f"💰 Multiplicateur GP ×{profile.gp_multiplier:.1f}")

        # Skill passive bonuses
        for skill in user.skills:
            pts = skill.points
            tag = skill.tag.value if hasattr(skill.tag, "value") else skill.tag
            emoji = TAG_EMOJI.get(tag, "▪")
            if pts >= 50:
                lines.append(f"{emoji} Compétence **{tag}** ≥ 50 pts : bonus passif actif")
            if pts >= 100:
                lines.append(f"{emoji} Compétence **{tag}** = 100 pts : bonus maximal débloqué")

        if not lines:
            lines.append("Aucun bonus actif pour le moment.")

        embed = discord.Embed(
            title="✨ Bonus passifs actifs",
            description="\n".join(lines),
            color=COLOR_INFO,
        )
        await interaction.followup.send(embed=embed, ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(RPGCog(bot))
