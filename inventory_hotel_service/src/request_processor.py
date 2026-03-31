import asyncio
import json
import logging
import math
from collections import defaultdict
from datetime import datetime
from typing import Any, Awaitable, Callable

from amadeus_sender import AmadeusSender
from cfg import Cfg
from debug_messages import DebugPublisher, emit_debug_message

logger = logging.getLogger("inventory_hotel_service.request_processor")
StatusPublisher = Callable[[str], Awaitable[None]]


class _ProgressTracker:
    """Asyncio-safe counter that publishes a status message after each increment."""

    def __init__(
        self,
        total: int | None,
        status_publisher: StatusPublisher | None,
    ) -> None:
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
            if self._total is not None:
                await self._status_publisher(
                    f"Fetching hotel options: {done}/{self._total} requests processed."
                )
            else:
                await self._status_publisher(
                    f"Fetching hotel options: {done} requests processed."
                )
        except Exception:
            logger.warning("Failed to publish hotel progress status", exc_info=True)


def _parse_iso_dt(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        if value.endswith("Z"):
            value = value[:-1] + "+00:00"
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _parse_location_latlng(value: Any) -> tuple[float, float] | None:
    if isinstance(value, dict):
        lat = value.get("lat", value.get("latitude"))
        lng = value.get("lng", value.get("longitude", value.get("lobgitude")))
        if lat is None or lng is None:
            return None
        return (float(lat), float(lng))
    if isinstance(value, (list, tuple)) and len(value) == 2:
        return (float(value[0]), float(value[1]))
    if isinstance(value, str) and "," in value:
        first, second = value.split(",", 1)
        return (float(first.strip()), float(second.strip()))
    return None


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
    return offer.get("available") is True


def _select_nearest_hotel_ids(
    hotel_ids: list[str],
    distance_index: dict[str, float],
    limit: int = 10,
) -> list[str]:
    sorted_ids = sorted(hotel_ids, key=lambda hid: distance_index.get(hid, math.inf))
    return sorted_ids[:limit]


def _extract_structured_request(payload: dict[str, Any]) -> dict[str, Any]:
    # Prefer trip request from structured_response.output or structured_request.output.
    for key in ("structured_response", "structured_request"):
        structured = payload.get(key)
        if not isinstance(structured, dict):
            continue
        output = structured.get("output")
        if isinstance(output, dict):
            return output
        # Backward-compat: use full object if it has trip (e.g. legacy payloads).
        if isinstance(structured.get("trip"), dict):
            return structured
    raise ValueError(
        "Incoming payload must contain object field 'structured_request.output' or 'structured_response.output' (trip request)"
    )


def _extract_source_flights(payload: dict[str, Any]) -> list[dict[str, Any]]:
    response = payload.get("provider_flight_response")
    if not isinstance(response, dict):
        return []
    raw = response.get("flights")
    if not isinstance(raw, list):
        return []
    return [x for x in raw if isinstance(x, dict)]


def _extract_stays(structured_request: dict[str, Any]) -> list[dict[str, Any]]:
    trip = structured_request.get("trip")
    if not isinstance(trip, dict):
        return []
    stays = trip.get("stays")
    if not isinstance(stays, list):
        return []
    return [x for x in stays if isinstance(x, dict)]


def _date_part(dt_str: str) -> str:
    s = str(dt_str).strip()
    return s[:10] if len(s) >= 10 else s


def _seg_dep_iata(seg: dict[str, Any]) -> str:
    dep = seg.get("departure")
    if isinstance(dep, dict):
        code = dep.get("iataCode")
        if isinstance(code, str) and code.strip():
            return code.strip().upper()
    return ""


def _seg_arr_iata(seg: dict[str, Any]) -> str:
    arr = seg.get("arrival")
    if isinstance(arr, dict):
        code = arr.get("iataCode")
        if isinstance(code, str) and code.strip():
            return code.strip().upper()
    return ""


def _seg_dep_at(seg: dict[str, Any]) -> str:
    dep = seg.get("departure")
    if isinstance(dep, dict):
        at = dep.get("at")
        if isinstance(at, str) and at.strip():
            return at.strip()
    return ""


def _seg_arr_at(seg: dict[str, Any]) -> str:
    arr = seg.get("arrival")
    if isinstance(arr, dict):
        at = arr.get("at")
        if isinstance(at, str) and at.strip():
            return at.strip()
    return ""


# Same-city / metro aliases as itinerary_composer (hotel stays keyed by e.g. LON).
_METRO_AIRPORT_GROUPS: tuple[frozenset[str], ...] = (
    frozenset({"LHR", "LCY", "LGW", "STN", "LTN", "LON", "SEN"}),
    frozenset({"JFK", "LGA", "EWR", "SWF", "NYC"}),
    frozenset({"CDG", "ORY", "BVA", "PAR"}),
    frozenset({"NRT", "HND", "TYO"}),
    frozenset({"SFO", "OAK", "SJC"}),
)


def _accumulate_city_date_for_stays(
    bucket: dict[str, set[str]],
    city: str,
    d: str,
) -> None:
    city_u = city.upper().strip()
    if not city_u or not d:
        return
    bucket.setdefault(city_u, set()).add(d)
    for group in _METRO_AIRPORT_GROUPS:
        if city_u in group:
            for alias in group:
                bucket.setdefault(alias, set()).add(d)
            break


def _flight_group_has_multi_itinerary_offer(fg: dict[str, Any]) -> bool:
    if str(fg.get("flight_kind", "")).strip().lower() == "round_trip":
        return True
    for o in fg.get("options", []) or []:
        if not isinstance(o, dict):
            continue
        itins = o.get("itineraries")
        if isinstance(itins, list) and len(itins) >= 2:
            return True
    return False


def _accumulate_gap_dates_from_multi_itinerary_offers(
    fg: dict[str, Any],
    arrive_dates_by_dest: dict[str, set[str]],
    depart_dates_by_origin: dict[str, set[str]],
) -> None:
    """
    For full round-trip offers (2+ itineraries), group-level from/to/dates do not describe
    the destination stay window. Use last arrival of itinerary 1 and first departure of
    itinerary 2 so stays (e.g. city LON) get correct check-in / check-out dates.
    """
    for opt in fg.get("options", []) or []:
        if not isinstance(opt, dict):
            continue
        itins = opt.get("itineraries")
        if not isinstance(itins, list) or len(itins) < 2:
            continue
        it0 = itins[0]
        it1 = itins[1]
        if not isinstance(it0, dict) or not isinstance(it1, dict):
            continue
        segs0 = it0.get("segments")
        segs1 = it1.get("segments")
        if not isinstance(segs0, list) or not segs0 or not isinstance(segs1, list) or not segs1:
            continue
        last0 = segs0[-1]
        first1 = segs1[0]
        arr_ap = _seg_arr_iata(last0)
        dep_ap = _seg_dep_iata(first1)
        arr_dt = _seg_arr_at(last0)
        dep_dt = _seg_dep_at(first1)
        if not arr_ap or not dep_ap or not arr_dt or not dep_dt:
            continue
        d_arr = _date_part(arr_dt)
        d_dep = _date_part(dep_dt)
        _accumulate_city_date_for_stays(arrive_dates_by_dest, arr_ap, d_arr)
        _accumulate_city_date_for_stays(depart_dates_by_origin, dep_ap, d_dep)


def _build_stays_from_flight_groups(
    flight_groups: list[dict[str, Any]],
    stays: list[dict[str, Any]],
    currency: str,
    travelers: int,
) -> list[dict[str, Any]]:
    arrive_dates_by_dest: dict[str, set[str]] = defaultdict(set)
    depart_dates_by_origin: dict[str, set[str]] = defaultdict(set)

    for fg in flight_groups:
        if _flight_group_has_multi_itinerary_offer(fg):
            _accumulate_gap_dates_from_multi_itinerary_offers(
                fg, arrive_dates_by_dest, depart_dates_by_origin
            )
            continue
        to_code = str(fg.get("to", "")).strip().upper()
        from_code = str(fg.get("from", "")).strip().upper()
        arrive_date = str(fg.get("arrive_date", "")).strip()
        depart_date = str(fg.get("depart_date", "")).strip()
        if to_code and arrive_date:
            arrive_dates_by_dest[to_code].add(arrive_date)
        if from_code and depart_date:
            depart_dates_by_origin[from_code].add(depart_date)

    built: list[dict[str, Any]] = []
    for stay in stays:
        city_code = str(stay.get("city_code", "")).strip().upper()
        if not city_code:
            continue

        arrival_dates = sorted(arrive_dates_by_dest.get(city_code, set()))
        departure_dates = sorted(depart_dates_by_origin.get(city_code, set()))
        if not arrival_dates or not departure_dates:
            continue

        duration_days = int(stay.get("duration", 0) or 0)
        valid_pairs: list[tuple[str, str, int]] = []
        for check_in in arrival_dates:
            in_dt = _parse_iso_dt(check_in)
            if in_dt is None:
                continue
            for check_out in departure_dates:
                out_dt = _parse_iso_dt(check_out)
                if out_dt is None or out_dt <= in_dt:
                    continue
                stay_days = (out_dt.date() - in_dt.date()).days
                valid_pairs.append((check_in, check_out, stay_days))

        if not valid_pairs:
            continue

        selected_pairs = valid_pairs
        if duration_days > 0:
            exact_pairs = [x for x in valid_pairs if x[2] == duration_days]
            if exact_pairs:
                selected_pairs = exact_pairs

        for check_in, check_out, _stay_days in selected_pairs:
            built.append(
                {
                    "check_in": check_in,
                    "check_out": check_out,
                    "min_rooms": int(stay.get("min_rooms", 1) or 1),
                    "travelers": travelers,
                    "currency": currency,
                    "city_code": city_code,
                    "location_latlng": stay.get("location_latlng"),
                    "city": stay.get("city"),
                }
            )

    deduped: dict[str, dict[str, Any]] = {}
    for stay in built:
        stay_key = json.dumps(
            {
                "check_in": stay.get("check_in"),
                "check_out": stay.get("check_out"),
                "city_code": stay.get("city_code"),
                "location_latlng": stay.get("location_latlng"),
                "travelers": stay.get("travelers"),
                "min_rooms": stay.get("min_rooms"),
                "currency": stay.get("currency"),
            },
            sort_keys=True,
        )
        if stay_key not in deduped:
            deduped[stay_key] = stay
    return list(deduped.values())


def _build_hotel_request(stay: dict[str, Any], cfg: Cfg) -> dict[str, Any]:
    latlng = _parse_location_latlng(stay.get("location_latlng"))
    if latlng is not None:
        lat, lng = latlng
        return {
            "hotels_list_mode": "geocode",
            "query_params": {
                "latitude": lat,
                "longitude": lng,
                "radius": cfg.amadeus_hotels_latlng_radius_km,
                "radiusUnit": "KM",
                "hotelSource": "ALL",
            },
            "stay": stay,
        }

    city_code = str(stay.get("city_code", "")).strip().upper()
    if not city_code:
        raise ValueError("Stay is missing required field: city_code or location_latlng")
    return {
        "hotels_list_mode": "city",
        "query_params": {
            "cityCode": city_code,
            "radius": cfg.amadeus_hotels_citycode_radius_km,
            "radiusUnit": "KM",
            "hotelSource": "ALL",
        },
        "stay": stay,
    }


def _stay_cache_key(req: dict[str, Any]) -> str:
    stay = req.get("stay", {})
    qp = req.get("query_params", {})
    mode = req.get("hotels_list_mode", "city")
    return json.dumps(
        {
            "mode": mode,
            "query_params": qp,
            "check_in": stay.get("check_in"),
            "check_out": stay.get("check_out"),
            "travelers": stay.get("travelers"),
            "min_rooms": stay.get("min_rooms"),
            "currency": stay.get("currency"),
        },
        sort_keys=True,
    )


async def _fetch_hotels_for_request(
    sender: AmadeusSender,
    cfg: Cfg,
    req: dict[str, Any],
    request_id: str | None,
    debug_publisher: DebugPublisher | None,
    progress_tracker: _ProgressTracker | None = None,
) -> list[dict[str, Any]]:
    stay = req.get("stay", {})
    mode = req.get("hotels_list_mode", "city")
    on_response = progress_tracker.report if progress_tracker is not None else None
    try:
        if mode == "geocode":
            hotels_list_response = await sender.send_hotels_list_by_geocode(
                query_params=req.get("query_params", {}),
                on_response=on_response,
            )
        else:
            hotels_list_response = await sender.send_hotels_list(
                query_params=req.get("query_params", {}),
                on_response=on_response,
            )
    except Exception as error:
        await emit_debug_message(
            debug_publisher,
            request_id,
            "Failed to fetch hotels list",
            level="error",
            payload={"request": req, "error": str(error)},
        )
        return []

    hotel_ids = _extract_hotel_ids(hotels_list_response)
    distance_index = _extract_distance_index(hotels_list_response)
    sorted_hotel_ids = _select_nearest_hotel_ids(hotel_ids, distance_index, limit=len(hotel_ids))
    chunk_size = max(1, cfg.amadeus_hotel_offers_max_chunk_size)

    adults = int(stay.get("travelers", 1) or 1)
    room_quantity = int(stay.get("min_rooms", 1) or 1)
    check_in = str(stay.get("check_in", "")).strip()
    check_out = str(stay.get("check_out", "")).strip()
    currency = str(stay.get("currency", "USD")).strip() or "USD"

    if cfg.amadeus_max_hotel_offers is not None:
        sorted_hotel_ids = sorted_hotel_ids[:cfg.amadeus_max_hotel_offers]

    hotel_id_chunks: list[list[str]] = []
    for offset in range(0, len(sorted_hotel_ids), chunk_size):
        hotel_ids_chunk = sorted_hotel_ids[offset : offset + chunk_size]
        if not hotel_ids_chunk:
            continue
        hotel_id_chunks.append(hotel_ids_chunk)

    async def _send_offers_for_chunk(chunk: list[str]) -> dict[str, Any]:
        return await sender.send_hotels_offers(
            query_params={
                "hotelIds": ",".join(chunk),
                "adults": adults,
                "checkInDate": check_in,
                "checkOutDate": check_out,
                "roomQuantity": room_quantity,
                "currency": currency,
                "includeClosed": True,
            },
            debug_publisher=debug_publisher,
            request_id=request_id,
            debug_extra={"request": req},
            on_response=on_response,
        )

    offers_tasks = [_send_offers_for_chunk(chunk) for chunk in hotel_id_chunks]

    all_offers: list[dict[str, Any]] = []
    if offers_tasks:
        offers_responses = await asyncio.gather(*offers_tasks, return_exceptions=True)
        for response in offers_responses:
            if isinstance(response, Exception):
                # Error debug is published from AmadeusSender.send_hotels_offers after retries.
                continue
            all_offers.extend(_collect_hotel_offers(response))

    filtered = [x for x in all_offers if _is_offer_available(x)]
    enriched: list[dict[str, Any]] = []
    for offer in filtered:
        offer_copy = dict(offer)
        offer_copy["_stay"] = {
            "city": stay.get("city"),
            "city_code": stay.get("city_code"),
            "check_in": check_in,
            "check_out": check_out,
        }
        enriched.append(offer_copy)
    return enriched


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
    source_flights = _extract_source_flights(payload)
    stays = _extract_stays(structured_request)

    trip = structured_request.get("trip", {})
    travelers = int(trip.get("travelers", 1) or 1) if isinstance(trip, dict) else 1
    budgets = structured_request.get("budgets", {})
    hotels_budget = budgets.get("hotels", {}) if isinstance(budgets, dict) else {}
    currency = str(hotels_budget.get("currency", "USD")).strip() or "USD"
    stays_for_hotels = _build_stays_from_flight_groups(
        source_flights,
        stays,
        currency,
        travelers,
    )
    cache: dict[str, list[dict[str, Any]]] = {}
    HotelGroupKey = tuple[str, str, str]
    hotel_groups: dict[HotelGroupKey, list[dict[str, Any]]] = {}
    progress_tracker = _ProgressTracker(None, status_publisher)
    for stay in stays_for_hotels:
        try:
            req = _build_hotel_request(stay, cfg)
        except Exception as error:
            await emit_debug_message(
                debug_publisher,
                request_id,
                "Failed to build hotel request for stay",
                level="error",
                payload={"stay": stay, "error": str(error)},
            )
            continue
        cache_key = _stay_cache_key(req)
        if cache_key not in cache:
            cache[cache_key] = await _fetch_hotels_for_request(
                sender,
                cfg,
                req,
                request_id,
                debug_publisher,
                progress_tracker=progress_tracker,
            )
        city_code = str(stay.get("city_code", "")).strip().upper()
        group_key: HotelGroupKey = (city_code, stay["check_in"], stay["check_out"])
        if group_key not in hotel_groups:
            hotel_groups[group_key] = []
        hotel_groups[group_key].extend(cache.get(cache_key, []))

    hotels_out: list[dict[str, Any]] = []
    for group_key in sorted(hotel_groups.keys()):
        city_code, check_in, check_out = group_key
        opts = hotel_groups[group_key]
        hotels_out.append(
            {
                "city_code": city_code,
                "check_in": check_in,
                "check_out": check_out,
                "options": [dict(x) for x in opts],
            }
        )

    logger.info(
        "Processed inventory hotel message for %d legs into %d stay combinations",
        len(source_flights),
        len(hotels_out),
    )
    return {"flights": source_flights, "hotels": hotels_out}
