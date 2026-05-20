"""Kafka consumer dispatch — routes incoming events to the correct service handler."""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Callable, Awaitable

from aiokafka import AIOKafkaConsumer

from bot.config import get_settings
from bot.kafka import topics

logger = logging.getLogger(__name__)

Handler = Callable[[dict], Awaitable[None]]
_registry: dict[str, dict[str, Handler]] = {}


def register(topic: str, event_type: str):
    """Decorator to register a handler for a specific topic + event_type."""
    def decorator(fn: Handler) -> Handler:
        _registry.setdefault(topic, {})[event_type] = fn
        return fn
    return decorator


async def _dispatch(topic: str, message: dict) -> None:
    event_type = message.get("event_type", "")
    handlers = _registry.get(topic, {})
    handler = handlers.get(event_type)
    if handler:
        try:
            await handler(message["payload"])
        except Exception:
            logger.exception("Handler error for %s / %s", topic, event_type)


async def run_consumer(subscribed_topics: list[str]) -> None:
    settings = get_settings()
    consumer = AIOKafkaConsumer(
        *subscribed_topics,
        bootstrap_servers=settings.kafka_bootstrap_servers,
        group_id=settings.kafka_group_id,
        value_deserializer=lambda v: json.loads(v.decode("utf-8")),
        auto_offset_reset="earliest",
    )
    await consumer.start()
    logger.info("Kafka consumer started for topics: %s", subscribed_topics)
    try:
        async for msg in consumer:
            await _dispatch(msg.topic, msg.value)
    finally:
        await consumer.stop()


async def start_all_consumers() -> asyncio.Task:
    """Start background consumer task for all registered topics."""
    subscribed = list(_registry.keys())
    if not subscribed:
        subscribed = topics.ALL_TOPICS
    return asyncio.create_task(run_consumer(subscribed))
