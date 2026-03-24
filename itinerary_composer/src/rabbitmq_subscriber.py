import json
import logging
from typing import Any

import aio_pika
from aio_pika import ExchangeType

from cfg import Cfg
from composer import compose_itinerary
from rabbitmq_publisher import (
    publish_composed_itinerary,
    publish_empty_itinerary,
    publish_status_message,
)

_EMPTY_ITINERARY_MESSAGE = (
    "No itinerary found for your request, please refine your request."
)

logger = logging.getLogger("itinerary_composer.rabbitmq_subscriber")


def _build_no_itineraries_payload(
    incoming: dict[str, Any],
    *,
    outer_request_id: str | None,
) -> dict[str, Any]:
    """Shape aligned with query_router llm_client (request_id, type, payload)."""
    sr = incoming.get("structured_request")
    structured_request_id: str | None = None
    if isinstance(sr, dict):
        rid = sr.get("request_id")
        if isinstance(rid, str) and rid.strip():
            structured_request_id = rid.strip()

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

    return {
        "id": correlation_id,
        "request_id": llm_request_id,
        "type": "no_itineraries",
        "payload": {
            "message": _EMPTY_ITINERARY_MESSAGE,
        },
    }


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

    composed = await compose_itinerary(
        payload,
        exchange_rate_latest_url=cfg.exchange_rate_latest_url,
    )
    itineraries = composed.get("itineraries", [])

    if not itineraries:
        await publish_empty_itinerary(
            exchange=exchange,
            routing_key=cfg.rabbitmq_empty_itinerary_routing_key,
            payload=_build_no_itineraries_payload(
                payload,
                outer_request_id=request_id if isinstance(request_id, str) else None,
            ),
        )
        return

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
