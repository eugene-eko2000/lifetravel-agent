import asyncio
import json
import logging
from typing import Any

import aio_pika
from aio_pika import ExchangeType

from amadeus_interval import AmadeusQueryInterval
from amadeus_sender import AmadeusSender
from cfg import Cfg
from request_processor import process_incoming_message
from rabbitmq_publisher import (
    publish_debug_message,
    publish_provider_response,
    publish_status_message,
)

# Backward-compat alias for existing tests/imports.
_process_incoming_message = process_incoming_message

logger = logging.getLogger("inventory_flight_service.rabbitmq_subscriber")

_RECONNECT_DELAY_SEC = 0.1


def _log_background_task(task: asyncio.Task[None]) -> None:
    try:
        exc = task.exception()
    except asyncio.CancelledError:
        return
    if exc is not None:
        logger.error(
            "Background inventory flight message task failed",
            exc_info=(type(exc), exc, exc.__traceback__),
        )


async def _process_flight_incoming(
    incoming: aio_pika.abc.AbstractIncomingMessage,
    exchange: aio_pika.abc.AbstractExchange,
    cfg: Cfg,
    sender: AmadeusSender,
) -> None:
    async with incoming.process():
        try:
            request_id = None
            incoming_payload = {}
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

            async def _status_publisher(message: str) -> None:
                await publish_status_message(
                    exchange=exchange,
                    routing_key=cfg.rabbitmq_status_routing_key,
                    payload={"id": request_id, "message": message},
                )

            results = await process_incoming_message(
                sender,
                cfg,
                incoming.body,
                request_id=request_id,
                debug_publisher=_debug_publisher,
                status_publisher=_status_publisher,
            )

            pfr: dict[str, Any] = {
                "flights": results.get("flights", []),
            }
            d = results.get("flight_dictionaries")
            if isinstance(d, dict) and d:
                pfr["flight_dictionaries"] = d
            outgoing_payload = {
                "id": request_id,
                "structured_request": incoming_payload.get("structured_request"),
                "prompt_id": incoming_payload.get("prompt_id"),
                "provider_flight_response": pfr,
            }
            await publish_provider_response(
                exchange=exchange,
                routing_key=cfg.rabbitmq_publish_routing_key,
                payload=outgoing_payload,
            )
        except Exception:
            logger.exception("Failed to process incoming inventory flight message")


async def run_inventory_subscriber() -> None:
    cfg = Cfg.from_env()
    query_interval: AmadeusQueryInterval | None = None
    if (
        cfg.amadeus_interval_between_queries is not None
        and cfg.amadeus_interval_between_queries > 0
    ):
        query_interval = AmadeusQueryInterval(cfg.amadeus_interval_between_queries)
    sender = AmadeusSender(cfg, query_interval=query_interval)

    logger.info(
        "Starting inventory flight RabbitMQ subscriber "
        "(exchange=%s, subscribe_key=%s, queue=%s)",
        cfg.rabbitmq_exchange,
        cfg.rabbitmq_subscribe_routing_key,
        cfg.rabbitmq_queue_name,
    )

    while True:
        try:
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
                        task = asyncio.create_task(
                            _process_flight_incoming(incoming, exchange, cfg, sender)
                        )
                        task.add_done_callback(_log_background_task)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception(
                "Inventory flight subscriber connection or consumer loop failed; reconnecting in %s s",
                _RECONNECT_DELAY_SEC,
            )
            await asyncio.sleep(_RECONNECT_DELAY_SEC)
