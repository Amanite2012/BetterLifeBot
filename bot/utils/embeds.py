"""Discord embed factory functions."""
from __future__ import annotations

from datetime import date, timedelta
from typing import TYPE_CHECKING

import discord

from bot.services.rpg import title_for_level, xp_required

if TYPE_CHECKING:
    from bot.database.models import (
        PenaltyRecord,
        SleepLog,
        User,
        UserProfile,
        UserSkill,
        HabitStreak,
    )

# Colour palette
COLOR_SUCCESS = discord.Color.green()
COLOR_WARNING = discord.Color.orange()
COLOR_DANGER = discord.Color.red()
COLOR_INFO = discord.Color.blurple()
COLOR_GOLD = discord.Color.gold()

PRIORITY_EMOJI = {"P1": "🔴", "P2": "🟠", "P3": "🟡", "P4": "⚪"}
STATUS_EMOJI = {
    "perfect": "✅", "near_complete": "🟡", "partial": "🟠",
    "insufficient": "🔴", "critical": "💀", "abandoned": "☠️",
}
TAG_EMOJI = {
    "work": "💼", "learning": "📚", "health": "💪",
    "creative": "🎨", "admin": "🗂️", "social": "🤝",
    "habit": "🔄", "none": "📌",
}


def build_profile_embed(user: "User") -> discord.Embed:
    profile: "UserProfile" = user.profile
    level = profile.level
    title = title_for_level(level)
    xp_next = xp_required(level + 1) if level < 50 else 0
    xp_current = xp_required(level)
    xp_progress = profile.xp - xp_current
    xp_needed = xp_next - xp_current if xp_next else 1

    bar_filled = int((xp_progress / xp_needed) * 20) if xp_needed else 20
    bar = "█" * bar_filled + "░" * (20 - bar_filled)

    embed = discord.Embed(
        title=f"⚔️ {title} — Niveau {level}",
        color=int(profile.embed_color.lstrip("#"), 16),
    )
    embed.add_field(name="XP", value=f"`{bar}` {xp_progress}/{xp_needed}", inline=False)
    embed.add_field(name="💰 GP", value=str(profile.gp), inline=True)
    embed.add_field(name="🎯 Volonté", value=f"Niv. {profile.willpower_level}", inline=True)

    # Skills
    if user.skills:
        skill_lines = "\n".join(
            f"{TAG_EMOJI.get(s.tag.value if hasattr(s.tag, 'value') else s.tag, '▪')} "
            f"**{s.tag.value if hasattr(s.tag, 'value') else s.tag}** — {s.points}/100"
            for s in user.skills
        )
        embed.add_field(name="🧠 Compétences", value=skill_lines or "—", inline=False)

    # Active modifiers
    mods = []
    if profile.sleep_xp_modifier != 1.0:
        mods.append(f"Sommeil: ×{profile.sleep_xp_modifier:.1f} XP")
    if profile.xp_multiplier != 1.0:
        mods.append(f"Boost: ×{profile.xp_multiplier:.1f} XP")
    if mods:
        embed.add_field(name="✨ Modificateurs actifs", value="\n".join(mods), inline=False)

    return embed


def build_penalty_embed(record: "PenaltyRecord") -> discord.Embed:
    status = record.status.value if hasattr(record.status, "value") else record.status
    emoji = STATUS_EMOJI.get(status, "❓")
    color = COLOR_DANGER if record.xp_penalty_pct >= 30 else COLOR_WARNING if record.xp_penalty_pct > 0 else COLOR_SUCCESS

    embed = discord.Embed(
        title=f"{emoji} Bilan du Jour — {record.record_date}",
        color=color,
    )
    embed.add_field(name="Complétion", value=f"{record.weighted_completion_pct:.0f}%", inline=True)
    embed.add_field(name="Statut", value=status.replace("_", " ").capitalize(), inline=True)

    if record.xp_penalty_pct > 0:
        embed.add_field(name="⬇️ Malus XP", value=f"−{record.xp_penalty_pct:.0f}% demain", inline=True)
    if record.gp_penalty > 0:
        embed.add_field(name="⬇️ Malus GP", value=f"−{record.gp_penalty} GP", inline=True)
    if record.recidive_day >= 2:
        embed.add_field(name="🔁 Récidive", value=f"Jour {record.recidive_day} (×{record.recidive_multiplier})", inline=True)
    if record.garmin_reduction:
        embed.add_field(name="🩺 Réduction Garmin", value="Malus ÷2 (fatigue détectée)", inline=True)
    if record.grace_day_used:
        embed.add_field(name="🛡️ Jour de grâce", value="Activé — pas de malus", inline=False)
    if record.vacation_mode:
        embed.add_field(name="🏖️ Mode vacances", value="Actif — pas de malus", inline=False)
    if record.redemption_next_day:
        embed.add_field(name="🌟 Rédemption", value="+30 XP bonus + malus annulé demain", inline=False)

    return embed


def build_sleep_embed(log: "SleepLog") -> discord.Embed:
    score = log.sleep_score
    if score >= 90:
        quality = "Excellent 🌟"
        color = COLOR_SUCCESS
    elif score >= 75:
        quality = "Bon 😊"
        color = discord.Color.teal()
    elif score >= 60:
        quality = "Acceptable 😐"
        color = COLOR_INFO
    elif score >= 40:
        quality = "Mauvais 😴"
        color = COLOR_WARNING
    else:
        quality = "Critique ⚠️"
        color = COLOR_DANGER

    hours = log.duration_minutes // 60
    minutes = log.duration_minutes % 60

    embed = discord.Embed(title=f"🌙 Sommeil — {log.sleep_date}", color=color)
    embed.add_field(name="Score", value=f"{score}/100 ({quality})", inline=True)
    embed.add_field(name="Durée", value=f"{hours}h{minutes:02d}", inline=True)
    embed.add_field(name="Cycles", value=str(log.sleep_cycles), inline=True)
    embed.add_field(name="Body Battery", value=f"{log.body_battery}/100", inline=True)
    embed.add_field(name="Stress", value=f"{log.stress_level}/100", inline=True)

    # RPG effect tomorrow
    if score >= 90:
        rpg = "XP ×1.3 + GP +15%"
    elif score >= 75:
        rpg = "XP ×1.1"
    elif score >= 60:
        rpg = "Aucun modificateur"
    elif score >= 40:
        rpg = "XP ×0.9"
    else:
        rpg = "XP ×0.8 + malus réduits −50%"
    embed.add_field(name="⚔️ Effet RPG demain", value=rpg, inline=False)

    return embed


def build_leaderboard_embed(entries: list[dict], lb_type: str) -> discord.Embed:
    embed = discord.Embed(
        title=f"🏆 Classement — {lb_type.upper()}",
        color=COLOR_GOLD,
    )
    lines = []
    medals = ["🥇", "🥈", "🥉"]
    for i, entry in enumerate(entries[:10]):
        medal = medals[i] if i < 3 else f"**{i+1}.**"
        lines.append(f"{medal} <@{entry['discord_id']}> — {entry['value']}")
    embed.description = "\n".join(lines) or "Aucune donnée."
    return embed
