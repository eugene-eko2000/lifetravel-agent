import json
from typing import Any

import aio_pika
from aio_pika import DeliveryMode, ExchangeType, Message

from cfg import Cfg


async def send_itinerary(payload: dict[str, Any]) -> None:
    cfg = Cfg.from_env()
    connection = await aio_pika.connect_robust(cfg.amqp_url)
    try:
        channel = await connection.channel()
        exchange = await channel.declare_exchange(
            cfg.rabbitmq_exchange,
            ExchangeType.DIRECT,
            durable=True,
        )

        body = json.dumps(payload).encode("utf-8")
        message = Message(body=body, delivery_mode=DeliveryMode.PERSISTENT)

        await exchange.publish(message, routing_key=cfg.rabbitmq_routing_key)
    finally:
        await connection.close()
