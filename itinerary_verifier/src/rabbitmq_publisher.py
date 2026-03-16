import json
import logging
from typing import Any

from aio_pika import DeliveryMode, Message
from aio_pika.abc import AbstractExchange

logger = logging.getLogger("itinerary_verifier.rabbitmq_publisher")


async def publish_verified_response(
    exchange: AbstractExchange,
    routing_key: str,
    payload: dict[str, Any],
) -> None:
    message = Message(
        body=json.dumps(payload).encode("utf-8"),
        delivery_mode=DeliveryMode.PERSISTENT,
        content_type="application/json",
    )
    await exchange.publish(message, routing_key=routing_key)
    logger.info("Published verified response via routing_key=%s", routing_key)


async def publish_adjusted_request(
    exchange: AbstractExchange,
    routing_key: str,
    payload: dict[str, Any],
) -> None:
    message = Message(
        body=json.dumps(payload).encode("utf-8"),
        delivery_mode=DeliveryMode.PERSISTENT,
        content_type="application/json",
    )
    await exchange.publish(message, routing_key=routing_key)
    logger.info("Published adjusted request via routing_key=%s", routing_key)
