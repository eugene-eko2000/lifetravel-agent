import asyncio
import json
import logging
import math
from typing import Any, Awaitable, Callable

from amadeus_sender import AmadeusSender
from cfg import Cfg
from request_translator import translate_trip_request_to_amadeus_requests

logger = logging.getLogger("inventory_flight_service.request_processor")
DebugPublisher = Callable[[dict[str, Any]], Awaitable[None]]


async def _emit_debug_message(
    debug_publisher: DebugPublisher | None,
    request_id: str | None,
    message: str,
    *,
    level: str,
    payload: dict[str, Any] | None = None,
) -> None:
    if debug_publisher is None:
        return
    if not isinstance(request_id, str) or not request_id.strip():
        return
    debug_payload: dict[str, Any] = {
        "id": request_id,
        "level": level,
        "source": "inventory_flight_service",
        "message": message,
    }
    if isinstance(payload, dict):
        debug_payload["payload"] = payload
    try:
        await debug_publisher(debug_payload)
    except Exception:
        logger.exception("Failed to publish debug message")


def _extract_hotel_ids(hotels_list_response: dict[str, Any]) -> list[str]:
    ids: list[str] = []
    data = hotels_list_response.get("data")
    if not isinstance(data, list):
        return ids

    for item in data:
        if not isinstance(item, dict):
            continue
        hotel_id = item.get("hotelId")
        if isinstance(hotel_id, str) and hotel_id:
            ids.append(hotel_id)
    return ids


def _extract_distance_index(hotels_list_response: dict[str, Any]) -> dict[str, float]:
    index: dict[str, float] = {}
    data = hotels_list_response.get("data")
    if not isinstance(data, list):
        return index

    for item in data:
        if not isinstance(item, dict):
            continue
        hotel_id = item.get("hotelId")
        if not isinstance(hotel_id, str) or not hotel_id:
            continue
        distance = item.get("distance")
        if isinstance(distance, dict):
            value = distance.get("value")
            if isinstance(value, (int, float)):
                index[hotel_id] = float(value)
    return index


def _collect_hotel_offers(offers_response: dict[str, Any]) -> list[dict[str, Any]]:
    data = offers_response.get("data")
    if not isinstance(data, list):
        return []
    return [item for item in data if isinstance(item, dict)]


def _is_offer_available(offer: dict[str, Any]) -> bool:
    if offer.get("error") is not None or offer.get("errors") is not None:
        return False

    available = offer.get("available")
    return available is True


def _select_nearest_hotel_ids(
    hotel_ids: list[str],
    distance_index: dict[str, float],
    limit: int = 10,
) -> list[str]:
    # Sort by known distance first (ascending). Unknown distances go last.
    sorted_ids = sorted(hotel_ids, key=lambda hid: distance_index.get(hid, math.inf))
    return sorted_ids[:limit]


def _extract_structured_request(payload: dict[str, Any]) -> dict[str, Any]:
    structured_response = payload.get("structured_response")
    if not isinstance(structured_response, dict):
        raise ValueError("Incoming payload must contain object field 'structured_response'")

    structured_output = structured_response.get("output")
    if not isinstance(structured_output, dict):
        raise ValueError(
            "Incoming payload must contain object field 'structured_response.output'"
        )

    return structured_output


async def _process_translated_request(
    sender: AmadeusSender,
    cfg: Cfg,
    translated: dict[str, Any],
    request_id: str | None = None,
    debug_publisher: DebugPublisher | None = None,
) -> Any:
    request_type = translated.get("type")

    if request_type == "flight":
        try:
            return await sender.send_flights_offers(
                payload=translated.get("payload", {}),
            )
        except Exception as error:
            await _emit_debug_message(
                debug_publisher,
                request_id,
                "Amadeus send_flights_offers failed",
                level="error",
                payload={
                    "request_type": request_type,
                    "translated": translated,
                    "error": str(error),
                },
            )
            raise

    if request_type == "hotel":
        hotel_mode = translated.get("hotels_list_mode", "city")
        stay = translated.get("stay", {}) if isinstance(translated.get("stay"), dict) else {}
        check_in = str(stay.get("check_in", "")).strip()
        check_out = str(stay.get("check_out", "")).strip()
        adults = int(stay.get("travelers", 1) or 1)
        room_quantity = int(stay.get("min_rooms", 1) or 1)
        currency = str(stay.get("currency", "USD")).strip() or "USD"

        if hotel_mode == "geocode":
            try:
                hotels_list_response = await sender.send_hotels_list_by_geocode(
                    query_params=translated.get("query_params", {}),
                )
            except Exception as error:
                await _emit_debug_message(
                    debug_publisher,
                    request_id,
                    "Amadeus send_hotels_list_by_geocode failed",
                    level="error",
                    payload={
                        "request_type": request_type,
                        "translated": translated,
                        "error": str(error),
                    },
                )
                raise
        else:
            try:
                hotels_list_response = await sender.send_hotels_list(
                    query_params=translated.get("query_params", {}),
                )
            except Exception as error:
                await _emit_debug_message(
                    debug_publisher,
                    request_id,
                    "Amadeus send_hotels_list failed",
                    level="error",
                    payload={
                        "request_type": request_type,
                        "translated": translated,
                        "error": str(error),
                    },
                )
                raise

        hotel_ids = _extract_hotel_ids(hotels_list_response)
        distance_index = _extract_distance_index(hotels_list_response)
        sorted_hotel_ids = _select_nearest_hotel_ids(
            hotel_ids,
            distance_index,
            limit=len(hotel_ids),
        )
        chunk_size = max(1, cfg.amadeus_hotels_offers_limit)

        offers_tasks = []
        for offset in range(0, len(sorted_hotel_ids), chunk_size):
            hotel_ids_chunk = sorted_hotel_ids[offset : offset + chunk_size]
            if not hotel_ids_chunk:
                continue

            offers_query = {
                "hotelIds": ",".join(hotel_ids_chunk),
                "adults": adults,
                "checkInDate": check_in,
                "checkOutDate": check_out,
                "roomQuantity": room_quantity,
                "currency": currency,
                "includeClosed": True,
            }
            offers_tasks.append(
                sender.send_hotels_offers(
                    query_params=offers_query,
                )
            )

        all_offers: list[dict[str, Any]] = []
        if offers_tasks:
            offers_responses = await asyncio.gather(*offers_tasks, return_exceptions=True)
            for response in offers_responses:
                if isinstance(response, Exception):
                    logger.exception("Failed to fetch hotel offers chunk", exc_info=response)
                    await _emit_debug_message(
                        debug_publisher,
                        request_id,
                        "Amadeus send_hotels_offers failed",
                        level="error",
                        payload={
                            "request_type": request_type,
                            "translated": translated,
                            "error": str(response),
                        },
                    )
                    continue
                all_offers.extend(_collect_hotel_offers(response))

        filtered_offers = [offer for offer in all_offers if _is_offer_available(offer)]

        return {
            "date": check_in or "unknown",
            "suggestions": filtered_offers,
            "raw_hotels_list": hotels_list_response,
        }

    logger.warning("Unknown translated request type: %s", request_type)
    return None


async def process_incoming_message(
    sender: AmadeusSender,
    cfg: Cfg,
    incoming_body: bytes,
    request_id: str | None = None,
    debug_publisher: DebugPublisher | None = None,
) -> dict[str, Any]:
    payload = json.loads(incoming_body.decode("utf-8"))
    structured_request = _extract_structured_request(payload)
    translated_requests = translate_trip_request_to_amadeus_requests(structured_request, cfg)
    results: dict[str, Any] = {
        "flights": [],
        "hotels": {},
    }
    flight_requests = [x for x in translated_requests if x.get("type") == "flight"]
    tasks = [
        _process_translated_request(
            sender,
            cfg,
            translated,
            request_id=request_id,
            debug_publisher=debug_publisher,
        )
        for translated in flight_requests
    ]
    processed_results = await asyncio.gather(*tasks, return_exceptions=True)

    for translated, result in zip(flight_requests, processed_results):
        if isinstance(result, Exception):
            logger.exception(
                "Failed to process translated request: %s",
                translated,
                exc_info=result,
            )
            await _emit_debug_message(
                debug_publisher,
                request_id,
                "Failed to process translated request",
                level="error",
                payload={
                    "translated": translated,
                    "error": str(result),
                },
            )
            continue

        request_type = translated.get("type")

        if request_type == "flight":
            results["flights"].append(result)
            continue

    logger.info(
        "Processed inventory flight message with %d translated requests (%d flight requests)",
        len(translated_requests),
        len(flight_requests),
    )
    return results
