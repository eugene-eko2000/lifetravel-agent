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
    for index, leg in enumerate(legs, start=1):
        if not isinstance(leg, dict):
            continue
        depart_dates = _leg_depart_dates(leg)
        if not depart_dates:
            raise ValueError(
                f"Leg #{index} is missing required field depart_dates (non-empty array of date strings)"
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
    return requests


def translate_trip_request_to_amadeus_requests(
    trip_request: dict[str, Any],
    cfg: Cfg,
) -> list[dict[str, Any]]:
    """
    Translate a structured Trip Request into downstream flight-only requests.
    One Amadeus call per (leg, depart_date) pair; same leg_index may repeat.
    """
    _ = cfg
    return _build_flight_requests(trip_request)
