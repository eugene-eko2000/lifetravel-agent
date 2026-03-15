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


def _build_flight_request_for_leg(
    leg: dict[str, Any],
    leg_index: int,
    travelers: list[dict[str, Any]],
) -> dict[str, Any]:
    origin = str(leg.get("from", "")).strip().upper()
    destination = str(leg.get("to", "")).strip().upper()
    depart_date = str(leg.get("depart_date", "")).strip()

    if not origin or not destination or not depart_date:
        raise ValueError(
            f"Leg #{leg_index} is missing required fields: from/to/depart_date"
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
        depart_date = str(leg.get("depart_date", "")).strip()
        requests.append(
            {
                "type": "flight",
                "method": "POST",
                "date": depart_date,
                "payload": _build_flight_request_for_leg(leg, index, travelers),
            }
        )
    return requests


def translate_trip_request_to_amadeus_requests(
    trip_request: dict[str, Any],
    cfg: Cfg,
) -> list[dict[str, Any]]:
    """
    Translate a structured Trip Request into downstream flight-only requests.
    """
    _ = cfg
    return _build_flight_requests(trip_request)
