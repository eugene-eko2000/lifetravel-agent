import json
import logging

import aio_pika
from aio_pika import ExchangeType

from amadeus_sender import AmadeusSender
from cfg import Cfg
from rabbitmq_publisher import publish_debug_message, publish_provider_response
from request_processor import process_incoming_message

logger = logging.getLogger("inventory_hotel_service.rabbitmq_subscriber")


async def run_inventory_hotel_subscriber() -> None:
    cfg = Cfg.from_env()
    sender = AmadeusSender(cfg)

    logger.info(
        "Starting inventory hotel RabbitMQ subscriber "
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
                        request_id = None
                        try:
                            incoming_payload = json.loads(incoming.body.decode("utf-8"))
                            candidate_request_id = incoming_payload.get("id")
                            if isinstance(candidate_request_id, str) and candidate_request_id.strip():
                                request_id = candidate_request_id
                        except Exception:
                            logger.warning("Failed to parse incoming payload for request id")

                        async def _debug_publisher(payload: dict) -> None:
                            await publish_debug_message(
                                exchange=exchange,
                                routing_key=cfg.rabbitmq_debug_routing_key,
                                payload=payload,
                            )

                        results = await process_incoming_message(
                            sender,
                            cfg,
                            incoming.body,
                            request_id=request_id,
                            debug_publisher=_debug_publisher,
                        )

                        await publish_provider_response(
                            exchange=exchange,
                            routing_key=cfg.rabbitmq_publish_routing_key,
                            payload={
                                "id": request_id,
                                "provider_response": results,
                            },
                        )
                    except Exception:
                        logger.exception("Failed to process incoming inventory hotel message")
