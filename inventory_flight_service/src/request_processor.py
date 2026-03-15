import asyncio
import json
import logging
from typing import Any, Awaitable, Callable

from amadeus_sender import AmadeusSender
from cfg import Cfg
from request_translator import translate_trip_request_to_amadeus_requests

logger = logging.getLogger("inventory_flight_service.request_processor")
DebugPublisher = Callable[[dict[str, Any]], Awaitable[None]]


class _QpsLimiter:
    def __init__(self, qps_limit: float) -> None:
        self._interval_sec = 1.0 / qps_limit
        self._lock = asyncio.Lock()
        self._next_allowed_ts = 0.0

    async def wait_for_slot(self) -> None:
        async with self._lock:
            now = asyncio.get_running_loop().time()
            if now < self._next_allowed_ts:
                await asyncio.sleep(self._next_allowed_ts - now)
            now = asyncio.get_running_loop().time()
            self._next_allowed_ts = now + self._interval_sec


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
    qps_limiter: _QpsLimiter | None = None,
) -> Any:
    request_type = translated.get("type")
    _ = cfg

    if request_type == "flight":
        try:
            if qps_limiter is not None:
                await qps_limiter.wait_for_slot()
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
    qps_limiter: _QpsLimiter | None = None
    if isinstance(cfg.amadeus_flights_qps_limit, (int, float)) and cfg.amadeus_flights_qps_limit > 0:
        qps_limiter = _QpsLimiter(float(cfg.amadeus_flights_qps_limit))
    tasks = [
        _process_translated_request(
            sender,
            cfg,
            translated,
            request_id=request_id,
            debug_publisher=debug_publisher,
            qps_limiter=qps_limiter,
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
            options = result.get("data") if isinstance(result, dict) else []
            if not isinstance(options, list):
                options = []
            results["flights"].append(
                {
                    "date": str(translated.get("date", "")),
                    "options": [x for x in options if isinstance(x, dict)],
                }
            )
            continue

    logger.info(
        "Processed inventory flight message with %d translated requests (%d flight requests)",
        len(translated_requests),
        len(flight_requests),
    )
    return results
