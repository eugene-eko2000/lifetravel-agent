import asyncio
import json
import logging
from typing import Any

import aio_pika
from aio_pika import ExchangeType

from cfg import Cfg
from rabbitmq_publisher import publish_ranked_response
from ranker import rank_provider_response

logger = logging.getLogger("ranking_service.rabbitmq_subscriber")


async def _process_message(incoming: aio_pika.abc.AbstractIncomingMessage, exchange: Any, cfg: Cfg) -> None:
    async with incoming.process():
        try:
            payload: dict[str, Any] = json.loads(incoming.body.decode("utf-8"))
            provider_response = payload.get("provider_response")
            if not isinstance(provider_response, dict):
                logger.warning(
                    "Skipping message without provider_response object: %s",
                    payload,
                )
                return

            ranked_response = rank_provider_response(provider_response)
            outgoing_payload = {
                "id": payload.get("id"),
                "ranked_response": ranked_response,
            }

            await publish_ranked_response(
                exchange=exchange,
                routing_key=cfg.rabbitmq_publish_routing_key,
                payload=outgoing_payload,
            )
        except Exception:
            logger.exception("Failed to process provider response message")


async def run_ranking_subscriber() -> None:
    cfg = Cfg.from_env()
    logger.info(
        "Starting ranking subscriber (exchange=%s, subscribe_key=%s, publish_key=%s, queue=%s)",
        cfg.rabbitmq_exchange,
        cfg.rabbitmq_subscribe_routing_key,
        cfg.rabbitmq_publish_routing_key,
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

        tasks: set[asyncio.Task[None]] = set()
        async with queue.iterator() as queue_iter:
            async for incoming in queue_iter:
                task = asyncio.create_task(_process_message(incoming, exchange, cfg))
                tasks.add(task)
                task.add_done_callback(tasks.discard)
