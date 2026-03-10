from typing import Any

from cfg import Cfg


def _build_flight_request(trip_request: dict[str, Any]) -> dict[str, Any]:
    trip = trip_request.get("trip", {})
    legs = trip.get("legs", [])

    origin_destinations: list[dict[str, Any]] = []
    for index, leg in enumerate(legs, start=1):
        origin = str(leg.get("from", "")).strip().upper()
        destination = str(leg.get("to", "")).strip().upper()
        depart_date = str(leg.get("depart_date", "")).strip()

        if not origin or not destination or not depart_date:
            raise ValueError(
                f"Leg #{index} is missing required fields: from/to/depart_date"
            )

        origin_destinations.append(
            {
                "id": str(index),
                "originLocationCode": origin,
                "destinationLocationCode": destination,
                "departureDateTimeRange": {
                    "date": depart_date,
                },
            }
        )

    travelers_count = int(trip.get("travelers", 1) or 1)
    travelers = [
        {
            "id": str(index),
            "travelerType": "ADULT",
            "fareOptions": ["STANDARD"],
        }
        for index in range(1, travelers_count + 1)
    ]

    return {
        "originDestinations": origin_destinations,
        "travelers": travelers,
        "sources": ["GDS"],
        "searchCriteria": {
            "maxFlightOffers": 10,
        },
    }


def translate_trip_request_to_amadeus_requests(
    trip_request: dict[str, Any],
    cfg: Cfg,
) -> list[dict[str, Any]]:
    """
    Translate a structured Trip Request into downstream flight-only requests.
    """
    _ = cfg
    flight_payload = _build_flight_request(trip_request)
    return [
        {
            "type": "flight",
            "method": "POST",
            "payload": flight_payload,
        }
    ]
