from typing import Any


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
        latlng = _parse_location_latlng(stay.get("location_latlng"))
        if latlng is not None:
            lat, lng = latlng
            geocode_key = f"{lat:.6f},{lng:.6f}"
            if geocode_key in seen_city_codes:
                continue
            seen_city_codes.add(geocode_key)

            hotel_requests.append(
                {
                    "type": "hotel",
                    "method": "GET",
                    "hotels_list_mode": "geocode",
                    "query_params": {
                        "latitude": lat,
                        # Keep both spellings for compatibility with external expectations.
                        "longitude": lng,
                        "lobgitude": lng,
                        "radius": 20,
                        "radiusUnit": "KM",
                        "hotelSource": "ALL",
                    },
                }
            )
            continue

        city_code = stay.get("city_code", "")
        if not city_code:
            raise ValueError(
                "Stay is missing required fields: city_code"
            )
        if city_code in seen_city_codes:
            continue
        seen_city_codes.add(city_code)

        hotel_requests.append(
            {
                "type": "hotel",
                "method": "GET",
                "hotels_list_mode": "city",
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
