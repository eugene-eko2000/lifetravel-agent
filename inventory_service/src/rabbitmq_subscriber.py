import json
import logging
from typing import Any

import aio_pika
from aio_pika import ExchangeType

from amadeus_sender import AmadeusSender
from cfg import Cfg
from request_translator import translate_trip_request_to_amadeus_requests

logger = logging.getLogger("inventory_service.rabbitmq_subscriber")


def _extract_structured_request(payload: dict[str, Any]) -> dict[str, Any]:
    if isinstance(payload.get("structured_request"), dict):
        return payload["structured_request"]

    if isinstance(payload.get("structured_response"), dict):
        structured_response = payload["structured_response"]
        if isinstance(structured_response.get("output"), dict):
            return structured_response["output"]
        if isinstance(structured_response.get("structured_request"), dict):
            return structured_response["structured_request"]

    if isinstance(payload.get("output"), dict):
        return payload["output"]

    raise ValueError("No structured request found in incoming message")


def _resolve_headers(payload: dict[str, Any], cfg: Cfg) -> dict[str, str]:
    payload_headers = payload.get("amadeus_headers")
    if isinstance(payload_headers, dict):
        return {str(k): str(v) for k, v in payload_headers.items()}

    if cfg.amadeus_auth_token:
        return {"Authorization": f"Bearer {cfg.amadeus_auth_token}"}

    return {}


async def _process_translated_request(
    sender: AmadeusSender,
    translated: dict[str, Any],
    headers: dict[str, str],
) -> None:
    request_type = translated.get("type")

    if request_type == "flight":
        await sender.send_flights_offers(
            payload=translated.get("payload", {}),
            headers=headers,
        )
        return

    if request_type == "hotel":
        hotel_mode = translated.get("hotels_list_mode", "city")
        if hotel_mode == "geocode":
            await sender.send_hotels_list_by_geocode(
                query_params=translated.get("query_params", {}),
                headers=headers,
            )
        else:
            await sender.send_hotels_list(
                query_params=translated.get("query_params", {}),
                headers=headers,
            )
        return

    logger.warning("Unknown translated request type: %s", request_type)


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
                        payload = json.loads(incoming.body.decode("utf-8"))
                        structured_request = _extract_structured_request(payload)
                        translated_requests = translate_trip_request_to_amadeus_requests(
                            structured_request
                        )
                        headers = _resolve_headers(payload, cfg)

                        for translated in translated_requests:
                            await _process_translated_request(sender, translated, headers)

                        logger.info(
                            "Processed inventory message with %d translated requests",
                            len(translated_requests),
                        )
                    except Exception:
                        logger.exception("Failed to process incoming inventory message")
