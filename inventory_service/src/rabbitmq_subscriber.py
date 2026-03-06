import logging

import aio_pika
from aio_pika import ExchangeType

from amadeus_sender import AmadeusSender
from cfg import Cfg
from request_processor import process_incoming_message

# Backward-compat alias for existing tests/imports.
_process_incoming_message = process_incoming_message

logger = logging.getLogger("inventory_service.rabbitmq_subscriber")


async def run_inventory_subscriber() -> None:
    cfg = Cfg.from_env()
    sender = AmadeusSender(cfg)

    logger.info(
        "Starting inventory RabbitMQ subscriber "
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
                        await process_incoming_message(sender, cfg, incoming.body)
                    except Exception:
                        logger.exception("Failed to process incoming inventory message")
