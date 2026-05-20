"""Seed default shop items."""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.database.models import ShopItem

DEFAULT_ITEMS = [
    ShopItem(name="Boost XP 2h", description="Double tes gains XP pendant 2 heures.", cost_gp=100, effect_type="xp_boost", effect_value=2.0, effect_duration_hours=2),
    ShopItem(name="Boost GP 24h", description="Augmente tes gains GP de 50% pendant 24h.", cost_gp=150, effect_type="gp_boost", effect_value=1.5, effect_duration_hours=24),
    ShopItem(name="Protection Streak", description="Protège ton streak quotidien pendant 3 jours.", cost_gp=200, effect_type="streak_protect", effect_value=3.0, effect_duration_hours=72),
    ShopItem(name="Annulation Malus", description="Annule le malus XP du lendemain.", cost_gp=300, effect_type="penalty_cancel", effect_value=1.0, effect_duration_hours=24),
    ShopItem(name="Couleur Embed", description="Personnalise la couleur de ton profil.", cost_gp=500, effect_type="embed_color", effect_value=0.0, effect_duration_hours=0),
]


async def seed_shop(session: AsyncSession) -> None:
    result = await session.execute(select(ShopItem))
    existing = result.scalars().all()
    if existing:
        return
    for item in DEFAULT_ITEMS:
        session.add(item)
    await session.commit()
