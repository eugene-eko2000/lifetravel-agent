import logging
from collections import defaultdict
from typing import Any

logger = logging.getLogger("itinerary_composer.composer")


def _date_part(dt_str: str) -> str:
    """Extract YYYY-MM-DD from a datetime or date string."""
    return dt_str[:10] if len(dt_str) >= 10 else dt_str


def _build_indexes(
    flight_groups: list[dict[str, Any]],
    hotel_groups: list[dict[str, Any]],
) -> tuple[
    dict[tuple[str, str], list[dict[str, Any]]],
    dict[tuple[str, str], list[dict[str, Any]]],
]:
    hotels_by_city_checkin: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for hg in hotel_groups:
        key = (hg.get("city_code", ""), hg.get("check_in", ""))
        hotels_by_city_checkin[key].append(hg)

    flights_by_origin_date: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for fg in flight_groups:
        key = (fg.get("from", ""), _date_part(fg.get("depart_date", "")))
        flights_by_origin_date[key].append(fg)

    return hotels_by_city_checkin, flights_by_origin_date


_MAX_ITINERARIES = 500


def _enumerate_chains(
    flight_groups: list[dict[str, Any]],
    hotels_by_city_checkin: dict[tuple[str, str], list[dict[str, Any]]],
    flights_by_origin_date: dict[tuple[str, str], list[dict[str, Any]]],
    start_origin: str,
    end_destination: str,
) -> list[dict[str, Any]]:
    itineraries: list[dict[str, Any]] = []

    def _dfs(
        chain_flights: list[dict[str, Any]],
        chain_hotels: list[dict[str, Any]],
        used_fg: set[int],
        used_hg: set[int],
    ) -> None:
        if len(itineraries) >= _MAX_ITINERARIES:
            return

        last_fg = chain_flights[-1]
        to_code = last_fg.get("to", "")
        arrive_date = _date_part(last_fg.get("arrive_date", ""))

        if to_code == end_destination:
            itineraries.append({
                "flights": list(chain_flights),
                "hotels": list(chain_hotels),
            })
            return

        matching_hotels = hotels_by_city_checkin.get((to_code, arrive_date), [])

        for hg in matching_hotels:
            if len(itineraries) >= _MAX_ITINERARIES:
                return
            hg_id = id(hg)
            if hg_id in used_hg:
                continue

            city_code = hg.get("city_code", "")
            check_out = hg.get("check_out", "")
            next_flights = flights_by_origin_date.get((city_code, check_out), [])

            for nfg in next_flights:
                nfg_id = id(nfg)
                if nfg_id in used_fg:
                    continue
                chain_flights.append(nfg)
                chain_hotels.append(hg)
                used_fg.add(nfg_id)
                used_hg.add(hg_id)
                _dfs(chain_flights, chain_hotels, used_fg, used_hg)
                chain_flights.pop()
                chain_hotels.pop()
                used_fg.discard(nfg_id)
                used_hg.discard(hg_id)

    for fg in flight_groups:
        if fg.get("from", "") == start_origin:
            _dfs([fg], [], {id(fg)}, set())

    return itineraries


def _extract_trip_endpoints(payload: dict[str, Any]) -> tuple[str, str]:
    """Return (start_origin, end_destination) from the structured request legs."""
    sr = payload.get("structured_request")
    if not isinstance(sr, dict):
        return "", ""
    output = sr.get("output", sr)
    if not isinstance(output, dict):
        return "", ""
    trip = output.get("trip")
    if not isinstance(trip, dict):
        return "", ""
    legs = trip.get("legs")
    if not isinstance(legs, list) or not legs:
        return "", ""
    first_leg = legs[0] if isinstance(legs[0], dict) else {}
    last_leg = legs[-1] if isinstance(legs[-1], dict) else {}
    return str(first_leg.get("from", "")), str(last_leg.get("to", ""))


async def compose_itinerary(payload: dict[str, Any]) -> dict[str, Any]:
    """Build all valid flight -> hotel -> flight -> ... chains from the inventory response."""
    provider_response = payload.get("provider_response")
    if not isinstance(provider_response, dict):
        logger.warning("No provider_response in payload (id=%s)", payload.get("id"))
        return {"itineraries": []}

    flight_groups = [fg for fg in provider_response.get("flights", []) if isinstance(fg, dict)]
    hotel_groups = [hg for hg in provider_response.get("hotels", []) if isinstance(hg, dict)]

    if not flight_groups:
        logger.info("No flight groups to compose (id=%s)", payload.get("id"))
        return {"itineraries": []}

    start_origin, end_destination = _extract_trip_endpoints(payload)
    if not start_origin or not end_destination:
        logger.warning(
            "Cannot determine trip start/end from structured_request (id=%s), "
            "start=%r end=%r",
            payload.get("id"),
            start_origin,
            end_destination,
        )
        return {"itineraries": []}

    hotels_by_city_checkin, flights_by_origin_date = _build_indexes(flight_groups, hotel_groups)
    itineraries = _enumerate_chains(
        flight_groups, hotels_by_city_checkin, flights_by_origin_date,
        start_origin, end_destination,
    )

    logger.info(
        "Composed %d itineraries from %d flight groups and %d hotel groups "
        "(start=%s, end=%s, id=%s)",
        len(itineraries),
        len(flight_groups),
        len(hotel_groups),
        start_origin,
        end_destination,
        payload.get("id"),
    )
    return {"itineraries": itineraries}
