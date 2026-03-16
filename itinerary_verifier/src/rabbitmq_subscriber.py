import json
import logging
from typing import Any

import aio_pika
from aio_pika import ExchangeType
from aio_pika.abc import AbstractExchange

from cfg import Cfg
from llm_client import request_structured_output
from rabbitmq_publisher import publish_adjusted_request, publish_verified_response

logger = logging.getLogger("itinerary_verifier.rabbitmq_subscriber")


async def _handle_message(payload: dict[str, Any], exchange: AbstractExchange, cfg: Cfg) -> None:
    request_id = str(payload.get("id", "") or "")
    structured_request = payload.get("structured_request")
    structured_request_obj = structured_request if isinstance(structured_request, dict) else {}
    prompt_id = str(structured_request_obj.get("prompt_id", "") or "")

    logger.info("Received provider response message for verification: %s", request_id)
    verification = await request_structured_output(
        request_id=request_id,
        prompt_id=prompt_id,
        content=json.dumps(payload),
    )
    verification_output = verification.get("output")
    output_obj = verification_output if isinstance(verification_output, dict) else {}
    match_ok = bool(output_obj.get("match_ok"))
    mismatches = output_obj.get("mismatches")
    mismatches_list = mismatches if isinstance(mismatches, list) else []

    if match_ok:
        await publish_verified_response(
            exchange=exchange,
            routing_key=cfg.rabbitmq_publish_verified_message_routing_key,
            payload={
                "id": request_id,
                "structured_request": structured_request_obj,
                "provider_response": payload.get("provider_response"),
                "verification": {
                    "match_ok": True,
                },
            },
        )
        return

    adjusted = output_obj.get("adjusted_structured_request")
    adjusted_structured_request = adjusted if isinstance(adjusted, dict) else {}
    await publish_adjusted_request(
        exchange=exchange,
        routing_key=cfg.rabbitmq_publish_adjusted_request_routing_key,
        payload={
            "id": request_id,
            "structured_request": {
                "request_id": request_id,
                "prompt_id": str(verification.get("prompt_id", "") or ""),
                "type": "valid_request",
                "output": adjusted_structured_request,
            },
            "verification": {
                "match_ok": False,
                "mismatches": mismatches_list,
            },
        },
    )


async def run_itinerary_verifier_subscriber() -> None:
    cfg = Cfg.from_env()
    logger.info(
        "Starting itinerary verifier subscriber (exchange=%s, subscribe_key=%s, queue=%s)",
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
                        payload: dict[str, Any] = json.loads(incoming.body.decode("utf-8"))
                        await _handle_message(payload, exchange, cfg)
                    except Exception:
                        logger.exception("Failed to process itinerary verifier message")
