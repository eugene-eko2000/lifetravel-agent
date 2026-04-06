import copy
import json
import logging
from typing import Any

import aio_pika
from aio_pika import ExchangeType

from cfg import Cfg
from composer import compose_trip
from rabbitmq_publisher import (
    publish_composed_trip,
    publish_empty_trip,
    publish_status_message,
)

_EMPTY_TRIP_MESSAGE = (
    "No trip found for your request, please refine your request."
)

logger = logging.getLogger("trip_composer.rabbitmq_subscriber")


def _build_no_trips_payload(
    incoming: dict[str, Any],
    *,
    outer_request_id: str | None,
) -> dict[str, Any]:
    """Shape aligned with query_router llm_client (request_id, type, payload)."""
    sr = incoming.get("structured_request")
    structured_request_id: str | None = None
    prompt_id: str | None = None
    if isinstance(sr, dict):
        rid = sr.get("request_id")
        if isinstance(rid, str) and rid.strip():
            structured_request_id = rid.strip()
        pid = sr.get("prompt_id")
        if isinstance(pid, str) and pid.strip():
            prompt_id = pid.strip()
    top_pid = incoming.get("prompt_id")
    if isinstance(top_pid, str) and top_pid.strip():
        prompt_id = top_pid.strip()

    correlation_id = (
        outer_request_id.strip()
        if isinstance(outer_request_id, str) and outer_request_id.strip()
        else None
    )
    if correlation_id is None and structured_request_id is not None:
        correlation_id = structured_request_id
    if correlation_id is None:
        correlation_id = ""

    llm_request_id = structured_request_id if structured_request_id is not None else correlation_id

    out: dict[str, Any] = {
        "id": correlation_id,
        "request_id": llm_request_id,
        "type": "no_trips",
        "payload": {
            "message": _EMPTY_TRIP_MESSAGE,
        },
    }
    if prompt_id:
        out["prompt_id"] = prompt_id
    return out


async def _handle_message(
    cfg: Cfg,
    exchange: aio_pika.abc.AbstractExchange,
    payload: dict[str, Any],
) -> None:
    request_id = payload.get("id")

    await publish_status_message(
        exchange=exchange,
        routing_key=cfg.rabbitmq_status_routing_key,
        payload={"id": request_id, "message": "Composing trip..."},
    )

    composed = await compose_trip(
        payload,
        exchange_rate_latest_url=cfg.exchange_rate_latest_url,
    )
    trips = composed.get("trips", [])

    if not trips:
        await publish_empty_trip(
            exchange=exchange,
            routing_key=cfg.rabbitmq_empty_trip_routing_key,
            payload=_build_no_trips_payload(
                payload,
                outer_request_id=request_id if isinstance(request_id, str) else None,
            ),
        )
        return

    logger.info(
        "Publishing %d trips separately (id=%s)",
        len(trips),
        request_id,
    )

    for idx, trip in enumerate(trips):
        composed_payload: dict[str, Any] = {
            "id": request_id,
            "trip_index": idx,
            "trip_count": len(trips),
            "trip": trip,
        }
        sr_in = payload.get("structured_request")
        if isinstance(sr_in, dict):
            composed_payload["structured_request"] = copy.deepcopy(sr_in)
        pid = trip.get("prompt_id")
        if isinstance(pid, str) and pid.strip():
            composed_payload["prompt_id"] = pid.strip()
        await publish_composed_trip(
            exchange=exchange,
            routing_key=cfg.rabbitmq_publish_routing_key,
            payload=composed_payload,
        )


async def run_subscriber() -> None:
    cfg = Cfg.from_env()

    logger.info(
        "Starting trip composer RabbitMQ subscriber "
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
                            "Failed to process incoming trip composer message"
                        )
