import asyncio
import json
import logging
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

def _extract_structured_request(payload: dict[str, Any]) -> dict[str, Any]:
    structured_request = payload.get("structured_request")
    if not isinstance(structured_request, dict):
        raise ValueError("Incoming payload must contain object field 'structured_request'")
    output = structured_request.get("output")
    if not isinstance(output, dict):
        raise ValueError(
            "Incoming payload must contain object field 'structured_request.output' (trip request)"
        )
    return output


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
