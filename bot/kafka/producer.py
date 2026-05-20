from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

from aiokafka import AIOKafkaProducer

from bot.config import get_settings

logger = logging.getLogger(__name__)

_producer: AIOKafkaProducer | None = None


async def get_producer() -> AIOKafkaProducer:
    global _producer
    if _producer is None:
        settings = get_settings()
        _producer = AIOKafkaProducer(
            bootstrap_servers=settings.kafka_bootstrap_servers,
            value_serializer=lambda v: json.dumps(v).encode("utf-8"),
            key_serializer=lambda k: k.encode("utf-8") if k else None,
        )
        await _producer.start()
    return _producer


async def publish(topic: str, event_type: str, payload: dict, key: str | None = None) -> None:
    producer = await get_producer()
    message = {
        "event_type": event_type,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "payload": payload,
    }
    try:
        await producer.send_and_wait(topic, value=message, key=key)
    except Exception:
        logger.exception("Failed to publish Kafka message to %s", topic)


async def close_producer() -> None:
    global _producer
    if _producer:
        await _producer.stop()
        _producer = None
