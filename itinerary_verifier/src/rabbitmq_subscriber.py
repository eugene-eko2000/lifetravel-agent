import json
import logging
from typing import Any

import aio_pika
from aio_pika import ExchangeType
from aio_pika.abc import AbstractExchange

from cfg import Cfg
from rabbitmq_publisher import publish_adjusted_request, publish_verified_response

logger = logging.getLogger("itinerary_verifier.rabbitmq_subscriber")


async def _handle_message(payload: dict[str, Any], exchange: AbstractExchange, cfg: Cfg) -> None:
    """Stub handler for future itinerary verification logic."""
    logger.info("Received provider response message (stub): %s", payload.get("id"))
    await publish_verified_response(
        exchange=exchange,
        routing_key=cfg.rabbitmq_publish_verified_message_routing_key,
        payload={},
    )
    await publish_adjusted_request(
        exchange=exchange,
        routing_key=cfg.rabbitmq_publish_adjusted_request_routing_key,
        payload={},
    )


async def run_itinerary_verifier_subscriber() -> None:
    cfg = Cfg.from_env()
    logger.info(
        "Starting itinerary verifier subscriber (exchange=%s, subscribe_key=%s, queue=%s)",
        cfg.rabbitmq_exchange,
        cfg.rabbitmq_subscribe_routing_key,
        cfg.rabbitmq_queue_name,
    )

    connection = await aio_pika.connect_robust(cfg.amqp_url)
    async with connection:
        channel = await connection.channel()
        exchange = await channel.declare_exchange(
            cfg.rabbitmq_exchange,
            ExchangeType.DIRECT,
            durable=True,
        )
        queue = await channel.declare_queue(cfg.rabbitmq_queue_name, durable=True)
        await queue.bind(exchange, routing_key=cfg.rabbitmq_subscribe_routing_key)

        async with queue.iterator() as queue_iter:
            async for incoming in queue_iter:
                async with incoming.process():
                    try:
                        payload: dict[str, Any] = json.loads(incoming.body.decode("utf-8"))
                        await _handle_message(payload, exchange, cfg)
                    except Exception:
                        logger.exception("Failed to process itinerary verifier message")
