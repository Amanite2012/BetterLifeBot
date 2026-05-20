from __future__ import annotations

import base64
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Discord
    discord_token: str
    discord_guild_id: int | None = None

    # Database
    database_url: str = "postgresql+asyncpg://betterlife:password@db:5432/betterlife"

    # Kafka
    kafka_bootstrap_servers: str = "kafka:9092"
    kafka_group_id: str = "betterlifebot"

    # Todoist
    todoist_client_id: str = ""
    todoist_client_secret: str = ""
    todoist_webhook_secret: str = ""

    # Garmin
    garmin_consumer_key: str = ""
    garmin_consumer_secret: str = ""
    garmin_oauth_callback_url: str = ""

    # Google Calendar
    google_client_id: str = ""
    google_client_secret: str = ""
    google_redirect_uri: str = ""

    # OpenWeather
    openweather_api_key: str = ""

    # Security
    encryption_key: str = ""  # base64-encoded 32-byte key

    # Webhook server
    webhook_host: str = "0.0.0.0"
    webhook_port: int = 8080
    public_base_url: str = "https://yourdomain.com"

    # Behaviour
    default_sleep_goal_hours: int = 8
    body_battery_poll_interval_hours: int = 4

    def encryption_key_bytes(self) -> bytes:
        return base64.b64decode(self.encryption_key)


@lru_cache
def get_settings() -> Settings:
    return Settings()
