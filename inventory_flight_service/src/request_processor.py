import asyncio
import json
import logging
from collections import defaultdict
from typing import Any, Awaitable, Callable

from amadeus_sender import AmadeusSender
from cfg import Cfg
from request_translator import translate_trip_request_to_amadeus_requests

logger = logging.getLogger("inventory_flight_service.request_processor")
DebugPublisher = Callable[[dict[str, Any]], Awaitable[None]]
StatusPublisher = Callable[[str], Awaitable[None]]


class _ProgressTracker:
    """Asyncio-safe counter that publishes a status message after each increment."""

    def __init__(self, total: int, status_publisher: StatusPublisher | None) -> None:
        self._total = total
        self._done = 0
        self._lock = asyncio.Lock()
        self._status_publisher = status_publisher

    async def report(self) -> None:
        async with self._lock:
            self._done += 1
            done = self._done
        if self._status_publisher is None:
            return
        try:
            await self._status_publisher(
                f"Fetching flight options: {done}/{self._total} requests processed."
            )
        except Exception:
            logger.warning("Failed to publish flight progress status", exc_info=True)


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

def _option_depart_dt(option: dict[str, Any]) -> str:
    """Departure datetime of the 1st segment of the first itinerary."""
    itineraries = option.get("itineraries")
    if not isinstance(itineraries, list) or not itineraries:
        return ""
    segments = itineraries[0].get("segments")
    if not isinstance(segments, list) or not segments:
        return ""
    dep = segments[0].get("departure")
    if isinstance(dep, dict):
        at = dep.get("at")
        if isinstance(at, str) and at.strip():
            return at.strip()
    return ""


def _option_arrive_dt(option: dict[str, Any]) -> str:
    """Arrival datetime of the last segment of the first itinerary."""
    itineraries = option.get("itineraries")
    if not isinstance(itineraries, list) or not itineraries:
        return ""
    segments = itineraries[0].get("segments")
    if not isinstance(segments, list) or not segments:
        return ""
    arr = segments[-1].get("arrival")
    if isinstance(arr, dict):
        at = arr.get("at")
        if isinstance(at, str) and at.strip():
            return at.strip()
    return ""


def _date_part(dt_str: str) -> str:
    """Extract the YYYY-MM-DD date portion from a datetime string."""
    return dt_str[:10] if len(dt_str) >= 10 else dt_str


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
    _ = cfg

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
    status_publisher: StatusPublisher | None = None,
) -> dict[str, Any]:
    payload = json.loads(incoming_body.decode("utf-8"))
    structured_request = _extract_structured_request(payload)
    translated_requests = translate_trip_request_to_amadeus_requests(structured_request, cfg)
    results: dict[str, Any] = {
        "flights": [],
    }
    flight_requests = [x for x in translated_requests if x.get("type") == "flight"]
    tracker = _ProgressTracker(len(flight_requests), status_publisher)

    async def _tracked(translated: dict[str, Any]) -> Any:
        try:
            return await _process_translated_request(
                sender,
                cfg,
                translated,
                request_id=request_id,
                debug_publisher=debug_publisher,
            )
        finally:
            await tracker.report()

    tasks = [_tracked(t) for t in flight_requests]
    processed_results = await asyncio.gather(*tasks, return_exceptions=True)

    GroupKey = tuple[str, str, str, str]
    groups: dict[GroupKey, list[dict[str, Any]]] = defaultdict(list)
    group_depart_dt: dict[GroupKey, str] = {}
    group_arrive_dt: dict[GroupKey, str] = {}

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

        if translated.get("type") != "flight":
            continue

        origin = str(translated.get("from", ""))
        destination = str(translated.get("to", ""))
        options = result.get("data") if isinstance(result, dict) else []
        if not isinstance(options, list):
            options = []
        for opt in options:
            if not isinstance(opt, dict):
                continue
            dep_dt = _option_depart_dt(opt)
            arr_dt = _option_arrive_dt(opt)
            key: GroupKey = (origin, destination, _date_part(dep_dt), _date_part(arr_dt))
            groups[key].append(opt)
            if key not in group_depart_dt and dep_dt:
                group_depart_dt[key] = _date_part(dep_dt)
                group_arrive_dt[key] = _date_part(arr_dt)

    for key in sorted(groups.keys(), key=lambda k: (k[2], k[3], k[0], k[1])):
        origin, destination, _, _ = key
        opts = groups[key]
        results["flights"].append(
            {
                "depart_date": group_depart_dt.get(key, ""),
                "arrive_date": group_arrive_dt.get(key, ""),
                "from": origin,
                "to": destination,
                "options": opts,
            }
        )

    logger.info(
        "Processed inventory flight message with %d translated requests (%d flight requests), %d legs",
        len(translated_requests),
        len(flight_requests),
        len(results["flights"]),
    )
    return results
