import json
import logging
from typing import Any

import aio_pika
from aio_pika import ExchangeType

from amadeus_sender import AmadeusSender
from cfg import Cfg
from request_translator import translate_trip_request_to_amadeus_requests

logger = logging.getLogger("inventory_service.rabbitmq_subscriber")


def _derive_city_code(city: str) -> str:
    sanitized = "".join(ch for ch in city.upper() if ch.isalpha())
    return sanitized[:3]


def _parse_location_latlng(value: Any) -> tuple[float, float] | None:
    if isinstance(value, dict):
        lat = value.get("lat", value.get("latitude"))
        lng = value.get("lng", value.get("longitude", value.get("lobgitude")))
        if lat is None or lng is None:
            return None
        return float(lat), float(lng)

    if isinstance(value, (list, tuple)) and len(value) == 2:
        return float(value[0]), float(value[1])

    if isinstance(value, str) and "," in value:
        first, second = value.split(",", 1)
        return float(first.strip()), float(second.strip())

    return None


def _build_hotel_dates_index(structured_request: dict[str, Any]) -> dict[str, list[str]]:
    trip = structured_request.get("trip", {})
    stays = trip.get("stays", [])

    index: dict[str, set[str]] = {}
    for stay in stays:
        if not isinstance(stay, dict):
            continue

        check_in = str(stay.get("check_in", "")).strip()
        if not check_in:
            continue

        city_code = str(stay.get("city_code", "")).strip().upper()
        if not city_code:
            city = str(stay.get("city", "")).strip()
            if city:
                city_code = _derive_city_code(city)
        if city_code:
            index.setdefault(f"city:{city_code}", set()).add(check_in)

        latlng = _parse_location_latlng(stay.get("location_latlng"))
        if latlng is not None:
            lat, lng = latlng
            index.setdefault(f"geo:{lat:.6f},{lng:.6f}", set()).add(check_in)

    return {key: sorted(value) for key, value in index.items()}


def _resolve_hotel_dates(
    translated: dict[str, Any],
    hotel_dates_index: dict[str, list[str]],
) -> list[str]:
    mode = translated.get("hotels_list_mode", "city")
    query_params = translated.get("query_params", {})

    if mode == "geocode":
        lat = query_params.get("latitude")
        lng = query_params.get("longitude", query_params.get("lobgitude"))
        if lat is not None and lng is not None:
            key = f"geo:{float(lat):.6f},{float(lng):.6f}"
            dates = hotel_dates_index.get(key)
            if dates:
                return dates
    else:
        city_code = str(query_params.get("cityCode", "")).strip().upper()
        if city_code:
            dates = hotel_dates_index.get(f"city:{city_code}")
            if dates:
                return dates

    return ["unknown"]


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
) -> Any:
    request_type = translated.get("type")

    if request_type == "flight":
        return await sender.send_flights_offers(
            payload=translated.get("payload", {}),
            headers=headers,
        )

    if request_type == "hotel":
        hotel_mode = translated.get("hotels_list_mode", "city")
        if hotel_mode == "geocode":
            return await sender.send_hotels_list_by_geocode(
                query_params=translated.get("query_params", {}),
                headers=headers,
            )

        return await sender.send_hotels_list(
            query_params=translated.get("query_params", {}),
            headers=headers,
        )

    logger.warning("Unknown translated request type: %s", request_type)
    return None


async def _process_incoming_message(
    sender: AmadeusSender,
    cfg: Cfg,
    incoming_body: bytes,
) -> dict[str, Any]:
    payload = json.loads(incoming_body.decode("utf-8"))
    structured_request = _extract_structured_request(payload)
    translated_requests = translate_trip_request_to_amadeus_requests(structured_request)
    headers = _resolve_headers(payload, cfg)
    hotel_dates_index = _build_hotel_dates_index(structured_request)

    results: dict[str, Any] = {
        "flights": [],
        "hotels": {},
    }
    for translated in translated_requests:
        result = await _process_translated_request(sender, translated, headers)
        request_type = translated.get("type")

        if request_type == "flight":
            results["flights"].append(result)
            continue

        if request_type == "hotel":
            for date_key in _resolve_hotel_dates(translated, hotel_dates_index):
                results["hotels"].setdefault(date_key, []).append(result)

    logger.info(
        "Processed inventory message with %d translated requests",
        len(translated_requests),
    )
    return results


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
                        await _process_incoming_message(sender, cfg, incoming.body)
                    except Exception:
                        logger.exception("Failed to process incoming inventory message")
