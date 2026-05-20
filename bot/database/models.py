"""SQLAlchemy ORM models for BetterLifeBot."""
from __future__ import annotations

import enum
from datetime import date, datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy.sql import func


class Base(DeclarativeBase):
    pass


# ── Enums ─────────────────────────────────────────────────────────────────────

class TaskPriority(str, enum.Enum):
    P1 = "P1"
    P2 = "P2"
    P3 = "P3"
    P4 = "P4"


class TaskTag(str, enum.Enum):
    WORK = "work"
    LEARNING = "learning"
    HEALTH = "health"
    CREATIVE = "creative"
    ADMIN = "admin"
    SOCIAL = "social"
    HABIT = "habit"
    NONE = "none"


class CompletionStatus(str, enum.Enum):
    PERFECT = "perfect"
    NEAR_COMPLETE = "near_complete"
    PARTIAL = "partial"
    INSUFFICIENT = "insufficient"
    CRITICAL = "critical"
    ABANDONED = "abandoned"


# ── Guild configuration ───────────────────────────────────────────────────────

class GuildConfig(Base):
    __tablename__ = "guild_configs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    guild_id: Mapped[int] = mapped_column(BigInteger, unique=True, nullable=False)
    habit_channel_id: Mapped[int | None] = mapped_column(BigInteger)
    discipline_channel_id: Mapped[int | None] = mapped_column(BigInteger)
    discipline_mention_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


# ── User & Character ──────────────────────────────────────────────────────────

class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    discord_id: Mapped[int] = mapped_column(BigInteger, unique=True, nullable=False)
    timezone: Mapped[str] = mapped_column(String(64), default="UTC")
    sleep_goal_hours: Mapped[float] = mapped_column(Float, default=8.0)
    private_only: Mapped[bool] = mapped_column(Boolean, default=False)
    todoist_user_id: Mapped[str | None] = mapped_column(String(64))
    todoist_access_token: Mapped[str | None] = mapped_column(Text)  # encrypted
    google_access_token: Mapped[str | None] = mapped_column(Text)   # encrypted
    google_refresh_token: Mapped[str | None] = mapped_column(Text)  # encrypted
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    profile: Mapped[UserProfile] = relationship("UserProfile", back_populates="user", uselist=False, cascade="all, delete-orphan")
    skills: Mapped[list[UserSkill]] = relationship("UserSkill", back_populates="user", cascade="all, delete-orphan")
    streaks: Mapped[list[HabitStreak]] = relationship("HabitStreak", back_populates="user", cascade="all, delete-orphan")
    daily_logs: Mapped[list[DailyLog]] = relationship("DailyLog", back_populates="user", cascade="all, delete-orphan")
    garmin_token: Mapped[GarminToken | None] = relationship("GarminToken", back_populates="user", uselist=False, cascade="all, delete-orphan")
    sleep_logs: Mapped[list[SleepLog]] = relationship("SleepLog", back_populates="user", cascade="all, delete-orphan")
    penalty_records: Mapped[list[PenaltyRecord]] = relationship("PenaltyRecord", back_populates="user", cascade="all, delete-orphan")
    willpower_challenges: Mapped[list[WillpowerChallenge]] = relationship("WillpowerChallenge", back_populates="user", cascade="all, delete-orphan")
    gratitude_entries: Mapped[list[GratitudeEntry]] = relationship("GratitudeEntry", back_populates="user", cascade="all, delete-orphan")
    grace_days: Mapped[list[GraceDay]] = relationship("GraceDay", back_populates="user", cascade="all, delete-orphan")
    vacation_modes: Mapped[list[VacationMode]] = relationship("VacationMode", back_populates="user", cascade="all, delete-orphan")
    recovery_challenges: Mapped[list[RecoveryChallenge]] = relationship("RecoveryChallenge", back_populates="user", cascade="all, delete-orphan")
    inventory: Mapped[list[UserInventory]] = relationship("UserInventory", back_populates="user", cascade="all, delete-orphan")


class UserProfile(Base):
    __tablename__ = "user_profiles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), unique=True, nullable=False)
    level: Mapped[int] = mapped_column(Integer, default=1)
    xp: Mapped[int] = mapped_column(Integer, default=0)
    gp: Mapped[int] = mapped_column(Integer, default=0)
    willpower_level: Mapped[int] = mapped_column(Integer, default=1)
    recidive_count: Mapped[int] = mapped_column(Integer, default=0)
    xp_multiplier: Mapped[float] = mapped_column(Float, default=1.0)
    xp_multiplier_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    gp_multiplier: Mapped[float] = mapped_column(Float, default=1.0)
    sleep_xp_modifier: Mapped[float] = mapped_column(Float, default=1.0)
    sleep_gp_bonus_pct: Mapped[float] = mapped_column(Float, default=0.0)
    next_xp_multiplier_use: Mapped[date | None] = mapped_column(Date)  # weekly savoir bonus
    embed_color: Mapped[str] = mapped_column(String(7), default="#5865F2")
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    user: Mapped[User] = relationship("User", back_populates="profile")


class UserSkill(Base):
    __tablename__ = "user_skills"
    __table_args__ = (UniqueConstraint("user_id", "tag", name="uq_user_skill_tag"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False)
    tag: Mapped[TaskTag] = mapped_column(Enum(TaskTag), nullable=False)
    points: Mapped[int] = mapped_column(Integer, default=0)  # 0–100

    user: Mapped[User] = relationship("User", back_populates="skills")


# ── Habit & Streak ────────────────────────────────────────────────────────────

class HabitStreak(Base):
    __tablename__ = "habit_streaks"
    __table_args__ = (UniqueConstraint("user_id", "streak_type", name="uq_user_streak_type"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False)
    streak_type: Mapped[str] = mapped_column(String(32), default="daily")  # daily, sport, sleep
    current_streak: Mapped[int] = mapped_column(Integer, default=0)
    longest_streak: Mapped[int] = mapped_column(Integer, default=0)
    last_completed: Mapped[date | None] = mapped_column(Date)
    protected_until: Mapped[date | None] = mapped_column(Date)  # Endurance skill protection
    monthly_grace_used: Mapped[bool] = mapped_column(Boolean, default=False)
    monthly_grace_reset: Mapped[date | None] = mapped_column(Date)

    user: Mapped[User] = relationship("User", back_populates="streaks")


class DailyLog(Base):
    __tablename__ = "daily_logs"
    __table_args__ = (UniqueConstraint("user_id", "log_date", "todoist_task_id", name="uq_daily_log"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False)
    log_date: Mapped[date] = mapped_column(Date, nullable=False)
    todoist_task_id: Mapped[str] = mapped_column(String(64), nullable=False)
    task_name: Mapped[str] = mapped_column(String(256), default="")
    tag: Mapped[TaskTag] = mapped_column(Enum(TaskTag), default=TaskTag.NONE)
    priority: Mapped[TaskPriority] = mapped_column(Enum(TaskPriority), default=TaskPriority.P4)
    is_recurring: Mapped[bool] = mapped_column(Boolean, default=False)
    completed: Mapped[bool] = mapped_column(Boolean, default=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    xp_earned: Mapped[int] = mapped_column(Integer, default=0)
    gp_earned: Mapped[int] = mapped_column(Integer, default=0)

    user: Mapped[User] = relationship("User", back_populates="daily_logs")


# ── Garmin ────────────────────────────────────────────────────────────────────

class GarminToken(Base):
    __tablename__ = "garmin_tokens"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), unique=True, nullable=False)
    access_token_enc: Mapped[str] = mapped_column(Text, nullable=False)   # AES-256 encrypted
    refresh_token_enc: Mapped[str] = mapped_column(Text, nullable=False)  # AES-256 encrypted
    token_expiry: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_sync: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    user: Mapped[User] = relationship("User", back_populates="garmin_token")


class SleepLog(Base):
    __tablename__ = "sleep_logs"
    __table_args__ = (UniqueConstraint("user_id", "sleep_date", name="uq_user_sleep_date"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False)
    sleep_date: Mapped[date] = mapped_column(Date, nullable=False)
    duration_minutes: Mapped[int] = mapped_column(Integer, default=0)
    bedtime: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    wake_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    sleep_score: Mapped[int] = mapped_column(Integer, default=0)        # 0–100
    body_battery: Mapped[int] = mapped_column(Integer, default=50)      # 0–100
    stress_level: Mapped[int] = mapped_column(Integer, default=25)      # 0–100
    hrv_avg: Mapped[float | None] = mapped_column(Float)
    sleep_cycles: Mapped[int] = mapped_column(Integer, default=0)
    rpg_modifier_applied: Mapped[bool] = mapped_column(Boolean, default=False)

    user: Mapped[User] = relationship("User", back_populates="sleep_logs")


# ── Penalties ─────────────────────────────────────────────────────────────────

class PenaltyRecord(Base):
    __tablename__ = "penalty_records"
    __table_args__ = (UniqueConstraint("user_id", "record_date", name="uq_user_penalty_date"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False)
    record_date: Mapped[date] = mapped_column(Date, nullable=False)
    weighted_completion_pct: Mapped[float] = mapped_column(Float, default=100.0)
    status: Mapped[CompletionStatus] = mapped_column(Enum(CompletionStatus), default=CompletionStatus.PERFECT)
    xp_penalty_pct: Mapped[float] = mapped_column(Float, default=0.0)
    gp_penalty: Mapped[int] = mapped_column(Integer, default=0)
    recidive_day: Mapped[int] = mapped_column(Integer, default=0)
    recidive_multiplier: Mapped[float] = mapped_column(Float, default=1.0)
    grace_day_used: Mapped[bool] = mapped_column(Boolean, default=False)
    vacation_mode: Mapped[bool] = mapped_column(Boolean, default=False)
    garmin_reduction: Mapped[bool] = mapped_column(Boolean, default=False)
    redemption_next_day: Mapped[bool] = mapped_column(Boolean, default=False)

    user: Mapped[User] = relationship("User", back_populates="penalty_records")


# ── Wellbeing ─────────────────────────────────────────────────────────────────

class WillpowerChallenge(Base):
    __tablename__ = "willpower_challenges"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    deadline_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    description: Mapped[str] = mapped_column(String(512), default="")
    completed: Mapped[bool | None] = mapped_column(Boolean)  # None = in progress
    level_before: Mapped[int] = mapped_column(Integer, nullable=False)

    user: Mapped[User] = relationship("User", back_populates="willpower_challenges")


class GratitudeEntry(Base):
    __tablename__ = "gratitude_entries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False)
    entry_date: Mapped[date] = mapped_column(Date, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    user: Mapped[User] = relationship("User", back_populates="gratitude_entries")


# ── Grace & Vacation ──────────────────────────────────────────────────────────

class GraceDay(Base):
    __tablename__ = "grace_days"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False)
    used_on: Mapped[date] = mapped_column(Date, nullable=False)

    user: Mapped[User] = relationship("User", back_populates="grace_days")


class VacationMode(Base):
    __tablename__ = "vacation_modes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False)
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date] = mapped_column(Date, nullable=False)
    quarter_year: Mapped[int] = mapped_column(Integer, nullable=False)

    user: Mapped[User] = relationship("User", back_populates="vacation_modes")


class RecoveryChallenge(Base):
    __tablename__ = "recovery_challenges"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False)
    todoist_task_id: Mapped[str] = mapped_column(String(64), nullable=False)
    task_name: Mapped[str] = mapped_column(String(256), default="")
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    deadline_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed: Mapped[bool | None] = mapped_column(Boolean)  # None = pending/offered

    user: Mapped[User] = relationship("User", back_populates="recovery_challenges")


# ── Shop ──────────────────────────────────────────────────────────────────────

class ShopItem(Base):
    __tablename__ = "shop_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="")
    cost_gp: Mapped[int] = mapped_column(Integer, nullable=False)
    effect_type: Mapped[str] = mapped_column(String(64), nullable=False)  # xp_boost, gp_boost, streak_protect, etc.
    effect_value: Mapped[float] = mapped_column(Float, default=0.0)
    effect_duration_hours: Mapped[int] = mapped_column(Integer, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class UserInventory(Base):
    __tablename__ = "user_inventory"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False)
    item_id: Mapped[int] = mapped_column(Integer, ForeignKey("shop_items.id"), nullable=False)
    purchased_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    activated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    user: Mapped[User] = relationship("User", back_populates="inventory")
    item: Mapped[ShopItem] = relationship("ShopItem")
