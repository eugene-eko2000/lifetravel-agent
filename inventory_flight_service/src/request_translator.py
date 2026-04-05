from typing import Any

from cfg import Cfg


# Structured LLM output (trip.cabin_preferences) → Amadeus Flight Offers Search
# cabin enum: ECONOMY, PREMIUM_ECONOMY, BUSINESS, FIRST
_CABIN_PREF_TO_AMADEUS: dict[str, str] = {
    "economy_light": "ECONOMY",
    "economy_standard": "ECONOMY",
    "economy_flex": "ECONOMY",
    "business": "BUSINESS",
    "first": "FIRST",
}


def _normalize_cabin_preferences(trip: dict[str, Any]) -> list[str]:
    """
    Map trip.cabin_preferences to Amadeus cabin codes (deduplicated, stable order).
    """
    raw = trip.get("cabin_preferences")
    if not isinstance(raw, list):
        return []
    seen: set[str] = set()
    out: list[str] = []
    for x in raw:
        key = str(x).strip().lower()
        code = _CABIN_PREF_TO_AMADEUS.get(key)
        if code is None or code in seen:
            continue
        seen.add(code)
        out.append(code)
    return out


def _normalize_airline_preferences(trip: dict[str, Any]) -> list[str]:
    """
    IATA airline codes for Amadeus carrierRestrictions.includedCarrierCodes (max 99).
    """
    raw = trip.get("airline_preferences")
    if not isinstance(raw, list):
        return []
    out: list[str] = []
    seen: set[str] = set()
    for x in raw:
        code = str(x).strip().upper()
        if len(code) < 2 or len(code) > 3:
            continue
        if code not in seen:
            seen.add(code)
            out.append(code)
    return out[:99]


def _cabin_restrictions_for_origin_destinations(
    amadeus_cabins: list[str],
    origin_destination_ids: list[str],
) -> list[dict[str, Any]]:
    """One CabinRestriction per distinct cabin; same OD ids as the request body."""
    ods = [str(x) for x in origin_destination_ids if str(x).strip()]
    if not ods:
        return []
    return [
        {
            "cabin": cabin,
            "coverage": "MOST_SEGMENTS",
            "originDestinationIds": ods,
        }
        for cabin in amadeus_cabins
    ]


def _build_search_criteria(
    airline_codes: list[str],
    amadeus_cabins: list[str],
    origin_destination_ids: list[str],
) -> dict[str, Any]:
    """
    Amadeus Flight Offers Search searchCriteria.
    Optional carrier whitelist and/or cabin restrictions (per Amadeus Flight Offers Search v2).
    """
    criteria: dict[str, Any] = {"maxFlightOffers": 250}
    flight_filters: dict[str, Any] = {}
    if airline_codes:
        flight_filters["carrierRestrictions"] = {
            "includedCarrierCodes": airline_codes,
        }
    if amadeus_cabins:
        flight_filters["cabinRestrictions"] = _cabin_restrictions_for_origin_destinations(
            amadeus_cabins,
            origin_destination_ids,
        )
    if flight_filters:
        criteria["flightFilters"] = flight_filters
    return criteria


def _build_travelers(trip_request: dict[str, Any]) -> list[dict[str, Any]]:
    trip = trip_request.get("trip", {})
    travelers_count = int(trip.get("travelers", 1) or 1)
    return [
        {
            "id": str(index),
            "travelerType": "ADULT",
            "fareOptions": ["STANDARD"],
        }
        for index in range(1, travelers_count + 1)
    ]


def _leg_depart_dates(leg: dict[str, Any]) -> list[str]:
    """Normalize to a non-empty list of date strings (YYYY-MM-DD)."""
    raw = leg.get("depart_dates")
    if isinstance(raw, list):
        out = [str(x).strip() for x in raw if str(x).strip()]
        if out:
            return out
    legacy = leg.get("depart_date")
    if legacy:
        s = str(legacy).strip()
        if s:
            return [s]
    return []


def _is_reverse_roundtrip_pair(leg_a: dict[str, Any], leg_b: dict[str, Any]) -> bool:
    """
    True when two consecutive legs are A→B and B→A (same airports, reversed).
    """
    a_from = str(leg_a.get("from", "")).strip().upper()
    a_to = str(leg_a.get("to", "")).strip().upper()
    b_from = str(leg_b.get("from", "")).strip().upper()
    b_to = str(leg_b.get("to", "")).strip().upper()
    if not a_from or not a_to or not b_from or not b_to:
        return False
    return a_from == b_to and a_to == b_from


def _build_roundtrip_flight_request_for_leg_pair(
    leg_out: dict[str, Any],
    leg_ret: dict[str, Any],
    leg_index_out: int,
    travelers: list[dict[str, Any]],
    outbound_date: str,
    return_date: str,
    search_criteria: dict[str, Any],
) -> dict[str, Any]:
    """Single Amadeus shopping request with outbound + return originDestinations."""
    o_a = str(leg_out.get("from", "")).strip().upper()
    o_b = str(leg_out.get("to", "")).strip().upper()
    if not o_a or not o_b or not outbound_date or not return_date:
        raise ValueError(
            f"Round-trip leg pair #{leg_index_out}/{leg_index_out + 1} is missing "
            "required fields: from/to/depart dates"
        )
    # leg_ret must be B→A; still validate against leg_out for safety
    if not _is_reverse_roundtrip_pair(leg_out, leg_ret):
        raise ValueError(
            f"Round-trip leg pair #{leg_index_out}/{leg_index_out + 1} is not A→B / B→A"
        )
    return {
        "originDestinations": [
            {
                "id": "1",
                "originLocationCode": o_a,
                "destinationLocationCode": o_b,
                "departureDateTimeRange": {
                    "date": outbound_date,
                },
            },
            {
                "id": "2",
                "originLocationCode": o_b,
                "destinationLocationCode": o_a,
                "departureDateTimeRange": {
                    "date": return_date,
                },
            },
        ],
        "travelers": travelers,
        "sources": ["GDS"],
        "searchCriteria": search_criteria,
    }


def _build_flight_request_for_leg(
    leg: dict[str, Any],
    leg_index: int,
    travelers: list[dict[str, Any]],
    depart_date: str,
    search_criteria: dict[str, Any],
) -> dict[str, Any]:
    origin = str(leg.get("from", "")).strip().upper()
    destination = str(leg.get("to", "")).strip().upper()

    if not origin or not destination or not depart_date:
        raise ValueError(
            f"Leg #{leg_index} is missing required fields: from/to/depart date"
        )

    return {
        "originDestinations": [
            {
                "id": "1",
                "originLocationCode": origin,
                "destinationLocationCode": destination,
                "departureDateTimeRange": {
                    "date": depart_date,
                },
            }
        ],
        "travelers": travelers,
        "sources": ["GDS"],
        "searchCriteria": search_criteria,
    }


def _build_flight_requests(trip_request: dict[str, Any]) -> list[dict[str, Any]]:
    trip = trip_request.get("trip", {})
    if not isinstance(trip, dict):
        trip = {}
    legs = trip.get("legs", [])
    travelers = _build_travelers(trip_request)
    airline_prefs = _normalize_airline_preferences(trip)
    cabin_prefs = _normalize_cabin_preferences(trip)
    search_criteria_one = _build_search_criteria(airline_prefs, cabin_prefs, ["1"])
    search_criteria_rt = _build_search_criteria(airline_prefs, cabin_prefs, ["1", "2"])

    requests: list[dict[str, Any]] = []
    i = 0
    while i < len(legs):
        leg = legs[i]
        index = i + 1
        if not isinstance(leg, dict):
            i += 1
            continue

        next_leg = legs[i + 1] if i + 1 < len(legs) else None
        if (
            isinstance(next_leg, dict)
            and _is_reverse_roundtrip_pair(leg, next_leg)
        ):
            depart_out = _leg_depart_dates(leg)
            depart_ret = _leg_depart_dates(next_leg)
            if not depart_out:
                raise ValueError(
                    f"Leg #{index} is missing required field depart_dates "
                    "(non-empty array of date strings)"
                )
            if not depart_ret:
                raise ValueError(
                    f"Leg #{index + 1} is missing required field depart_dates "
                    "(non-empty array of date strings)"
                )
            origin = str(leg.get("from", "")).strip().upper()
            destination = str(leg.get("to", "")).strip().upper()
            ret_from = str(next_leg.get("from", "")).strip().upper()
            ret_to = str(next_leg.get("to", "")).strip().upper()
            for outbound_date in depart_out:
                for return_date in depart_ret:
                    requests.append(
                        {
                            "type": "flight_roundtrip",
                            "method": "POST",
                            "outbound_date": outbound_date,
                            "return_date": return_date,
                            "leg_index_out": index,
                            "leg_index_return": index + 1,
                            "from": origin,
                            "to": destination,
                            "return_from": ret_from,
                            "return_to": ret_to,
                            "payload": _build_roundtrip_flight_request_for_leg_pair(
                                leg,
                                next_leg,
                                index,
                                travelers,
                                outbound_date,
                                return_date,
                                search_criteria_rt,
                            ),
                        }
                    )
            i += 2
            continue

        depart_dates = _leg_depart_dates(leg)
        if not depart_dates:
            raise ValueError(
                f"Leg #{index} is missing required field depart_dates "
                "(non-empty array of date strings)"
            )
        origin = str(leg.get("from", "")).strip().upper()
        destination = str(leg.get("to", "")).strip().upper()
        for depart_date in depart_dates:
            requests.append(
                {
                    "type": "flight",
                    "method": "POST",
                    "date": depart_date,
                    "leg_index": index,
                    "from": origin,
                    "to": destination,
                    "payload": _build_flight_request_for_leg(
                        leg, index, travelers, depart_date, search_criteria_one
                    ),
                }
            )
        i += 1
    return requests


def translate_trip_request_to_amadeus_requests(
    trip_request: dict[str, Any],
    cfg: Cfg,
) -> list[dict[str, Any]]:
    """
    Translate a structured Trip Request into downstream flight-only requests.

    Consecutive legs A→B and B→A are merged into one Amadeus round-trip request
    (two originDestinations) per (outbound depart date × return depart date).

    Other legs: one Amadeus call per (leg, depart_date) as before.

    When trip.airline_preferences is a non-empty array of IATA airline codes,
    each request includes searchCriteria.flightFilters.carrierRestrictions.includedCarrierCodes.

    When trip.cabin_preferences is set (economy_*, business, first), each request includes
    searchCriteria.flightFilters.cabinRestrictions for the corresponding Amadeus cabin codes
    (ECONOMY / BUSINESS / FIRST), scoped to the request's originDestination ids.
    """
    _ = cfg
    return _build_flight_requests(trip_request)
