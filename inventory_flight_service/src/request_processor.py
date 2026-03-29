import asyncio
import copy
import json
import logging
import re
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


def _halve_numeric_price_strings(price_dict: dict[str, Any]) -> None:
    """Halve common Amadeus price fields in-place (round-trip → per-leg share)."""
    for k in ("grandTotal", "total", "base"):
        v = price_dict.get(k)
        if isinstance(v, str) and v.strip():
            try:
                x = float(v)
                price_dict[k] = f"{x / 2.0:.2f}"
            except ValueError:
                pass
        elif isinstance(v, (int, float)):
            price_dict[k] = round(float(v) / 2.0, 2)


def _halve_prices_in_offer(option: dict[str, Any]) -> None:
    p = option.get("price")
    if isinstance(p, dict):
        _halve_numeric_price_strings(p)
    tps = option.get("travelerPricings")
    if isinstance(tps, list):
        for tp in tps:
            if isinstance(tp, dict) and isinstance(tp.get("price"), dict):
                _halve_numeric_price_strings(tp["price"])


def _segment_dep_iata(seg: dict[str, Any]) -> str:
    dep = seg.get("departure")
    if isinstance(dep, dict):
        code = dep.get("iataCode")
        if isinstance(code, str) and code.strip():
            return code.strip().upper()
    return ""


def _split_segments_for_roundtrip(
    segments: list[dict[str, Any]],
    *,
    return_from: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]] | None:
    """Split at first segment departing from return_from (second leg origin)."""
    rf = return_from.strip().upper()
    if not rf:
        return None
    j = None
    for idx, seg in enumerate(segments):
        if isinstance(seg, dict) and _segment_dep_iata(seg) == rf:
            j = idx
            break
    if j is None or j == 0:
        return None
    return segments[:j], segments[j:]


def _split_roundtrip_offer_to_legs(
    option: dict[str, Any],
    *,
    return_from: str,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """
    Split an Amadeus round-trip offer into outbound-only and return-only options.
    Prefers two itineraries; falls back to splitting segments in a single itinerary.
    Prices are halved per leg so downstream totals do not double-count RT fare.
    """
    itins = option.get("itineraries")
    if not isinstance(itins, list) or not itins:
        return None, None

    if len(itins) >= 2:
        out_itin = itins[0]
        ret_itin = itins[1]
        if not isinstance(out_itin, dict) or not isinstance(ret_itin, dict):
            return None, None
        out_opt = copy.deepcopy(option)
        out_opt["itineraries"] = [copy.deepcopy(out_itin)]
        ret_opt = copy.deepcopy(option)
        ret_opt["itineraries"] = [copy.deepcopy(ret_itin)]
        _halve_prices_in_offer(out_opt)
        _halve_prices_in_offer(ret_opt)
        return out_opt, ret_opt

    first = itins[0]
    if not isinstance(first, dict):
        return None, None
    segs = first.get("segments")
    if not isinstance(segs, list) or len(segs) < 2:
        return None, None
    split = _split_segments_for_roundtrip(segs, return_from=return_from)
    if split is None:
        return None, None
    out_segs, ret_segs = split
    out_itin = copy.deepcopy(first)
    out_itin["segments"] = list(out_segs)
    ret_itin = copy.deepcopy(first)
    ret_itin["segments"] = list(ret_segs)
    out_opt = copy.deepcopy(option)
    out_opt["itineraries"] = [out_itin]
    ret_opt = copy.deepcopy(option)
    ret_opt["itineraries"] = [ret_itin]
    _halve_prices_in_offer(out_opt)
    _halve_prices_in_offer(ret_opt)
    return out_opt, ret_opt


def _append_option_to_groups(
    groups: dict[tuple[str, str, str, str], list[dict[str, Any]]],
    group_depart_dt: dict[tuple[str, str, str, str], str],
    group_arrive_dt: dict[tuple[str, str, str, str], str],
    origin: str,
    destination: str,
    opt: dict[str, Any],
) -> None:
    dep_dt = _option_depart_dt(opt)
    arr_dt = _option_arrive_dt(opt)
    key = (origin, destination, _date_part(dep_dt), _date_part(arr_dt))
    groups[key].append(opt)
    if key not in group_depart_dt and dep_dt:
        group_depart_dt[key] = _date_part(dep_dt)
        group_arrive_dt[key] = _date_part(arr_dt)


def _offer_connection_count(offer: dict[str, Any]) -> int:
    """Total connection count across all itineraries (segments minus one per leg)."""
    itins = offer.get("itineraries")
    if not isinstance(itins, list):
        return 0
    n = 0
    for itin in itins:
        if not isinstance(itin, dict):
            continue
        segs = itin.get("segments")
        if not isinstance(segs, list):
            continue
        n += max(0, len(segs) - 1)
    return n


def _iso8601_duration_to_seconds(value: str) -> float:
    """Parse Amadeus itinerary duration (ISO-8601, e.g. PT5H30M, P1DT2H) to seconds."""
    if not isinstance(value, str) or not value.strip():
        return 0.0
    v = value.strip().upper()
    if not v.startswith("P"):
        return 0.0
    if "T" in v:
        date_part, time_part = v[1:].split("T", 1)
    else:
        date_part, time_part = v[1:], ""
    total = 0.0
    dm = re.search(r"(\d+)D", date_part)
    if dm:
        total += int(dm.group(1)) * 86400.0
    for m in re.finditer(r"(\d+(?:\.\d+)?)H", time_part):
        total += float(m.group(1)) * 3600.0
    for m in re.finditer(r"(\d+(?:\.\d+)?)M", time_part):
        total += float(m.group(1)) * 60.0
    for m in re.finditer(r"(\d+(?:\.\d+)?)S", time_part):
        total += float(m.group(1))
    return total


def _offer_total_duration_seconds(offer: dict[str, Any]) -> float:
    """Sum of per-itinerary duration fields (Amadeus)."""
    itins = offer.get("itineraries")
    if not isinstance(itins, list):
        return 0.0
    total = 0.0
    for itin in itins:
        if not isinstance(itin, dict):
            continue
        d = itin.get("duration")
        if isinstance(d, str):
            total += _iso8601_duration_to_seconds(d)
    return total


def _filter_and_limit_flight_offers(
    response: dict[str, Any],
    max_options: int,
) -> dict[str, Any]:
    """
    Sort offers by ascending connection count, then total flight time; keep the first
    max_options entries (Amadeus `data` list).
    """
    if not isinstance(response, dict):
        return response
    data = response.get("data")
    if not isinstance(data, list) or not data:
        return response
    cap = max(0, int(max_options))
    if cap == 0:
        out = dict(response)
        out["data"] = []
        return out
    valid = [x for x in data if isinstance(x, dict)]
    if not valid:
        return response
    valid.sort(
        key=lambda o: (
            _offer_connection_count(o),
            _offer_total_duration_seconds(o),
        )
    )
    out = dict(response)
    out["data"] = valid[:cap]
    return out


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

    if request_type in ("flight", "flight_roundtrip"):
        try:
            result = await sender.send_flights_offers(
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
        if isinstance(result, dict):
            result = _filter_and_limit_flight_offers(
                result,
                cfg.max_flight_options_per_fetch,
            )
        return result

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
    flight_requests = [
        x for x in translated_requests if x.get("type") in ("flight", "flight_roundtrip")
    ]
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

        if translated.get("type") not in ("flight", "flight_roundtrip"):
            continue

        options = result.get("data") if isinstance(result, dict) else []
        if not isinstance(options, list):
            options = []

        if translated.get("type") == "flight_roundtrip":
            origin_o = str(translated.get("from", ""))
            dest_o = str(translated.get("to", ""))
            origin_r = str(translated.get("return_from", ""))
            dest_r = str(translated.get("return_to", ""))
            for opt in options:
                if not isinstance(opt, dict):
                    continue
                out_opt, ret_opt = _split_roundtrip_offer_to_legs(
                    opt,
                    return_from=origin_r,
                )
                if out_opt is None or ret_opt is None:
                    logger.warning(
                        "Could not split round-trip offer into legs; skipping (offer id=%s)",
                        opt.get("id"),
                    )
                    continue
                _append_option_to_groups(
                    groups,
                    group_depart_dt,
                    group_arrive_dt,
                    origin_o,
                    dest_o,
                    out_opt,
                )
                _append_option_to_groups(
                    groups,
                    group_depart_dt,
                    group_arrive_dt,
                    origin_r,
                    dest_r,
                    ret_opt,
                )
            continue

        origin = str(translated.get("from", ""))
        destination = str(translated.get("to", ""))
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
