import json
import logging
import uuid
from typing import Any

import aio_pika
from aio_pika import DeliveryMode, ExchangeType, Message

from cfg import Cfg
from llm_client import request_structured_trip

logger = logging.getLogger("query_router.rabbitmq")


async def run_router() -> None:
    cfg = Cfg.from_env()
    logger.info(
        "Starting RabbitMQ router (exchange=%s, subscribe_key=%s, publish_key=%s)",
        cfg.rabbitmq_exchange,
        cfg.rabbitmq_subscribe_routing_key,
        cfg.rabbitmq_publish_routing_key,
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
                    await _handle_message(exchange, cfg, incoming.body)


async def _handle_message(
    exchange: aio_pika.abc.AbstractExchange,
    cfg: Cfg,
    raw_body: bytes,
) -> None:
    try:
        payload: dict[str, Any] = json.loads(raw_body.decode("utf-8"))
    except Exception:
        logger.exception("Failed to decode incoming RabbitMQ message")
        return

    content = payload.get("content")
    if not isinstance(content, str) or not content.strip():
        logger.error("Incoming message is missing a valid 'content' field: %s", payload)
        return

    request_id = payload.get("id")
    if not isinstance(request_id, str) or not request_id.strip():
        request_id = str(uuid.uuid4())
    status_payload = {
        "id": request_id,
        "message": "Analyzing your request...",
    }
    status_outgoing = Message(
        body=json.dumps(status_payload).encode("utf-8"),
        delivery_mode=DeliveryMode.PERSISTENT,
        content_type="application/json",
    )
    await exchange.publish(status_outgoing, routing_key=cfg.rabbitmq_status_routing_key)
    
    prompt_id = payload.get("prompt_id")

    try:
        llm_response = await request_structured_trip(request_id, prompt_id, content)
    except Exception:
        logger.exception("LLM processing failed")
        return

    outgoing_payload: dict[str, Any] = {
        "id": request_id,
        "content": content,
        "structured_request": llm_response,
        "prompt_id": llm_response.get("prompt_id"),
    }

    llm_response_type = llm_response.get("type")
    routing_key = (
        cfg.rabbitmq_missing_info_routing_key
        if llm_response_type == "missing_info"
        else cfg.rabbitmq_publish_routing_key
    )

    outgoing = Message(
        body=json.dumps(outgoing_payload).encode("utf-8"),
        delivery_mode=DeliveryMode.PERSISTENT,
        content_type="application/json",
    )
    await exchange.publish(outgoing, routing_key=routing_key)
    logger.info(
        "Published routed response for trip id=%s via routing_key=%s",
        request_id,
        routing_key,
    )

    debug_payload = {
        "id": request_id,
        "level": "debug",
        "source": "query_router",
        "message": "Structured request produced by LLM",
        "payload": {
            "structured_request": llm_response,
        },
    }
    debug_outgoing = Message(
        body=json.dumps(debug_payload).encode("utf-8"),
        delivery_mode=DeliveryMode.PERSISTENT,
        content_type="application/json",
    )
    await exchange.publish(debug_outgoing, routing_key=cfg.rabbitmq_debug_routing_key)
    logger.info("Published debug message for trip id=%s", request_id)
