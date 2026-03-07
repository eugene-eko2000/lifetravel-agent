import logging
import json

import aio_pika
from aio_pika import ExchangeType

from amadeus_sender import AmadeusSender
from cfg import Cfg
from request_processor import process_incoming_message
from rabbitmq_publisher import publish_provider_response

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
                        results = await process_incoming_message(sender, cfg, incoming.body)
                        request_id = None
                        try:
                            incoming_payload = json.loads(incoming.body.decode("utf-8"))
                            candidate_request_id = incoming_payload.get("id")
                            if isinstance(candidate_request_id, str) and candidate_request_id.strip():
                                request_id = candidate_request_id
                        except Exception:
                            logger.warning("Failed to parse incoming payload for request id")

                        outgoing_payload = {
                            "id": request_id,
                            "provider_response": results,
                        }
                        await publish_provider_response(
                            exchange=exchange,
                            routing_key=cfg.rabbitmq_publish_routing_key,
                            payload=outgoing_payload,
                        )
                    except Exception:
                        logger.exception("Failed to process incoming inventory message")
