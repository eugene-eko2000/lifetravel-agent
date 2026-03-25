from typing import Any

from cfg import Cfg


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
        "searchCriteria": {
            "maxFlightOffers": 10,
        },
    }


def _build_flight_request_for_leg(
    leg: dict[str, Any],
    leg_index: int,
    travelers: list[dict[str, Any]],
    depart_date: str,
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
        "searchCriteria": {
            "maxFlightOffers": 10,
        },
    }


def _build_flight_requests(trip_request: dict[str, Any]) -> list[dict[str, Any]]:
    trip = trip_request.get("trip", {})
    legs = trip.get("legs", [])
    travelers = _build_travelers(trip_request)

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
                        leg, index, travelers, depart_date
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
    """
    _ = cfg
    return _build_flight_requests(trip_request)
