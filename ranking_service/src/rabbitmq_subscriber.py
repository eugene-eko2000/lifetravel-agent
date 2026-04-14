import asyncio
import json
import logging
from typing import Any

import aio_pika
from aio_pika import ExchangeType

from cfg import Cfg
from rabbitmq_publisher import publish_ranked_trip, publish_status_message
from ranker import rank_single_trip

logger = logging.getLogger("ranking_service.rabbitmq_subscriber")

_RECONNECT_DELAY_SEC = 0.1


def _log_task_exception(task: asyncio.Task[None]) -> None:
    try:
        exc = task.exception()
    except asyncio.CancelledError:
        return
    if exc is not None:
        logger.error(
            "Background ranking task failed",
            exc_info=(type(exc), exc, exc.__traceback__),
        )


async def _process_message(incoming: aio_pika.abc.AbstractIncomingMessage, exchange: Any, cfg: Cfg) -> None:
    async with incoming.process():
        try:
            payload: dict[str, Any] = json.loads(incoming.body.decode("utf-8"))
            trip = payload.get("trip")
            if not isinstance(trip, dict):
                logger.warning(
                    "Skipping message without trip object: %s",
                    payload,
                )
                return

            await publish_status_message(
                exchange=exchange,
                routing_key=cfg.rabbitmq_status_routing_key,
                payload={
                    "id": payload.get("id"),
                    "message": "Ranking flight and hotel options...",
                },
            )

            sr = payload.get("structured_request")
            structured_request = sr if isinstance(sr, dict) else None
            ranked_trip = rank_single_trip(trip, structured_request=structured_request)
            outgoing_payload: dict[str, Any] = {
                "id": payload.get("id"),
                "trip_index": payload.get("trip_index"),
                "trip_count": payload.get("trip_count"),
                "ranked_trip": ranked_trip,
            }
            rpid = ranked_trip.get("prompt_id")
            if isinstance(rpid, str) and rpid.strip():
                outgoing_payload["prompt_id"] = rpid.strip()

            await publish_ranked_trip(
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

                tasks: set[asyncio.Task[None]] = set()
                async with queue.iterator() as queue_iter:
                    async for incoming in queue_iter:
                        task = asyncio.create_task(_process_message(incoming, exchange, cfg))
                        tasks.add(task)
                        task.add_done_callback(tasks.discard)
                        task.add_done_callback(_log_task_exception)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception(
                "Ranking subscriber connection or consumer loop failed; reconnecting in %s s",
                _RECONNECT_DELAY_SEC,
            )
            await asyncio.sleep(_RECONNECT_DELAY_SEC)
