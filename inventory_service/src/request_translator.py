from typing import Any


def _to_city_code(city: str) -> str:
    sanitized = "".join(ch for ch in city.upper() if ch.isalpha())
    if len(sanitized) < 3:
        raise ValueError(f"Cannot derive city code from city='{city}'")
    return sanitized[:3]


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


def _build_hotel_requests(trip_request: dict[str, Any]) -> list[dict[str, Any]]:
    trip = trip_request.get("trip", {})
    stays = trip.get("stays", [])

    # Keep first occurrence order while avoiding duplicate city queries.
    seen_city_codes: set[str] = set()
    hotel_requests: list[dict[str, Any]] = []

    for stay in stays:
        city = str(stay.get("city", "")).strip()
        if not city:
            continue

        city_code = _to_city_code(city)
        if city_code in seen_city_codes:
            continue
        seen_city_codes.add(city_code)

        hotel_requests.append(
            {
                "type": "hotel",
                "method": "GET",
                "query_params": {
                    "cityCode": city_code,
                    "radius": 20,
                    "radiusUnit": "KM",
                    "hotelSource": "ALL",
                },
            }
        )

    return hotel_requests


def translate_trip_request_to_amadeus_requests(
    trip_request: dict[str, Any],
) -> list[dict[str, Any]]:
    """
    Translate a structured Trip Request into downstream provider requests.

    Returns a list of request descriptors:
    - first item: flight request
    - next items: hotel requests
    """
    flight_payload = _build_flight_request(trip_request)
    hotel_requests = _build_hotel_requests(trip_request)

    return [
        {
            "type": "flight",
            "method": "POST",
            "payload": flight_payload,
        },
        *hotel_requests,
    ]
