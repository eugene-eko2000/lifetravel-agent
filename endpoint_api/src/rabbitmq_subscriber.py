import json
import logging
from typing import Any, Awaitable, Callable

import aio_pika
from aio_pika import ExchangeType

from cfg import Cfg

logger = logging.getLogger("endpoint_api.rabbitmq_subscriber")


async def run_missing_info_subscriber(
    on_message: Callable[[dict[str, Any]], Awaitable[None]],
) -> None:
    cfg = Cfg.from_env()
    logger.info(
        "Starting missing-info subscriber exchange=%s routing_key=%s queue=%s",
        cfg.rabbitmq_exchange,
        cfg.rabbitmq_missing_info_routing_key,
        cfg.rabbitmq_missing_info_queue,
    )

    connection = await aio_pika.connect_robust(cfg.amqp_url)
    async with connection:
        channel = await connection.channel()
        exchange = await channel.declare_exchange(
            cfg.rabbitmq_exchange,
            ExchangeType.DIRECT,
            durable=True,
        )
        queue = await channel.declare_queue(cfg.rabbitmq_missing_info_queue, durable=True)
        await queue.bind(exchange, routing_key=cfg.rabbitmq_missing_info_routing_key)

        async with queue.iterator() as queue_iter:
            async for incoming in queue_iter:
                async with incoming.process():
                    try:
                        payload: dict[str, Any] = json.loads(incoming.body.decode("utf-8"))
                    except Exception:
                        logger.exception("Invalid JSON in missing-info message")
                        continue

                    try:
                        await on_message(payload)
                    except Exception:
                        logger.exception("Failed handling missing-info message")


async def run_ranked_subscriber(
    on_message: Callable[[dict[str, Any]], Awaitable[None]],
) -> None:
    cfg = Cfg.from_env()
    logger.info(
        "Starting ranked subscriber exchange=%s routing_key=%s queue=%s",
        cfg.rabbitmq_exchange,
        cfg.rabbitmq_ranked_routing_key,
        cfg.rabbitmq_ranked_queue,
    )

    connection = await aio_pika.connect_robust(cfg.amqp_url)
    async with connection:
        channel = await connection.channel()
        exchange = await channel.declare_exchange(
            cfg.rabbitmq_exchange,
            ExchangeType.DIRECT,
            durable=True,
        )
        queue = await channel.declare_queue(cfg.rabbitmq_ranked_queue, durable=True)
        await queue.bind(exchange, routing_key=cfg.rabbitmq_ranked_routing_key)

        async with queue.iterator() as queue_iter:
            async for incoming in queue_iter:
                async with incoming.process():
                    try:
                        payload: dict[str, Any] = json.loads(incoming.body.decode("utf-8"))
                    except Exception:
                        logger.exception("Invalid JSON in ranked message")
                        continue

                    try:
                        await on_message(payload)
                    except Exception:
                        logger.exception("Failed handling ranked message")


async def run_debug_subscriber(
    on_message: Callable[[dict[str, Any]], Awaitable[None]],
) -> None:
    cfg = Cfg.from_env()
    logger.info(
        "Starting debug subscriber exchange=%s routing_key=%s queue=%s",
        cfg.rabbitmq_exchange,
        cfg.rabbitmq_debug_routing_key,
        cfg.rabbitmq_debug_queue,
    )

    connection = await aio_pika.connect_robust(cfg.amqp_url)
    async with connection:
        channel = await connection.channel()
        exchange = await channel.declare_exchange(
            cfg.rabbitmq_exchange,
            ExchangeType.DIRECT,
            durable=True,
        )
        queue = await channel.declare_queue(cfg.rabbitmq_debug_queue, durable=True)
        await queue.bind(exchange, routing_key=cfg.rabbitmq_debug_routing_key)

        async with queue.iterator() as queue_iter:
            async for incoming in queue_iter:
                async with incoming.process():
                    try:
                        payload: dict[str, Any] = json.loads(incoming.body.decode("utf-8"))
                    except Exception:
                        logger.exception("Invalid JSON in debug message")
                        continue

                    try:
                        await on_message(payload)
                    except Exception:
                        logger.exception("Failed handling debug message")


async def run_status_subscriber(
    on_message: Callable[[dict[str, Any]], Awaitable[None]],
) -> None:
    cfg = Cfg.from_env()
    logger.info(
        "Starting status subscriber exchange=%s routing_key=%s queue=%s",
        cfg.rabbitmq_exchange,
        cfg.rabbitmq_status_routing_key,
        cfg.rabbitmq_status_queue,
    )

    connection = await aio_pika.connect_robust(cfg.amqp_url)
    async with connection:
        channel = await connection.channel()
        exchange = await channel.declare_exchange(
            cfg.rabbitmq_exchange,
            ExchangeType.DIRECT,
            durable=True,
        )
        queue = await channel.declare_queue(cfg.rabbitmq_status_queue, durable=True)
        await queue.bind(exchange, routing_key=cfg.rabbitmq_status_routing_key)

        async with queue.iterator() as queue_iter:
            async for incoming in queue_iter:
                async with incoming.process():
                    try:
                        payload: dict[str, Any] = json.loads(incoming.body.decode("utf-8"))
                    except Exception:
                        logger.exception("Invalid JSON in status message")
                        continue

                    try:
                        await on_message(payload)
                    except Exception:
                        logger.exception("Failed handling status message")
