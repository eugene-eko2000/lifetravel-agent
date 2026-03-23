import json
import logging
from typing import Any

import aio_pika
from aio_pika import ExchangeType

from cfg import Cfg
from composer import compose_itinerary
from rabbitmq_publisher import (
    publish_composed_itinerary,
    publish_debug_message,
    publish_status_message,
)

logger = logging.getLogger("itinerary_composer.rabbitmq_subscriber")


async def _handle_message(
    cfg: Cfg,
    exchange: aio_pika.abc.AbstractExchange,
    payload: dict[str, Any],
) -> None:
    request_id = payload.get("id")

    await publish_status_message(
        exchange=exchange,
        routing_key=cfg.rabbitmq_status_routing_key,
        payload={"id": request_id, "message": "Composing itinerary..."},
    )

    composed = await compose_itinerary(payload)
    itineraries = composed.get("itineraries", [])

    logger.info(
        "Publishing %d itineraries separately (id=%s)",
        len(itineraries),
        request_id,
    )

    for idx, itinerary in enumerate(itineraries):
        await publish_composed_itinerary(
            exchange=exchange,
            routing_key=cfg.rabbitmq_publish_routing_key,
            payload={
                "id": request_id,
                "itinerary_index": idx,
                "itinerary_count": len(itineraries),
                "itinerary": itinerary,
            },
        )


async def run_subscriber() -> None:
    cfg = Cfg.from_env()

    logger.info(
        "Starting itinerary composer RabbitMQ subscriber "
        "(exchange=%s, subscribe_key=%s, queue=%s)",
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
                        incoming_payload = json.loads(incoming.body.decode("utf-8"))
                        await _handle_message(cfg, exchange, incoming_payload)
                    except Exception:
                        logger.exception(
                            "Failed to process incoming itinerary composer message"
                        )
