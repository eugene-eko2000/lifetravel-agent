"""
Integration-style unit tests for compose_trip: building trips from
flight groups and hotel groups in provider_response plus structured_request trip legs.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from typing import Any

PROJECT_DIR = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_DIR / "src"
sys.path.insert(0, str(SRC_DIR))

import composer as composer_module  # noqa: E402
from composer import compose_trip  # noqa: E402


def _flight_group(
    *,
    from_: str,
    to: str,
    depart_date: str,
    arrive_date: str,
    price: str = "100.00",
    currency: str = "USD",
) -> dict[str, Any]:
    return {
        "depart_date": depart_date,
        "arrive_date": arrive_date,
        "from": from_,
        "to": to,
        "options": [
            {
                "type": "flight-offer",
                "id": f"{from_}-{to}",
                "price": {"currency": currency, "grandTotal": price, "total": price},
                "itineraries": [{"duration": "PT2H", "segments": []}],
            }
        ],
    }


def _hotel_group(
    *,
    city_code: str,
    check_in: str,
    check_out: str,
    total: str = "80.00",
    currency: str = "USD",
) -> dict[str, Any]:
    return {
        "city_code": city_code,
        "check_in": check_in,
        "check_out": check_out,
        "options": [
            {
                "type": "hotel-offers",
                "offers": [
                    {
                        "checkInDate": check_in,
                        "checkOutDate": check_out,
                        "price": {"currency": currency, "total": total},
                    }
                ],
            }
        ],
    }


def _structured_payload(
    *,
    legs: list[dict[str, Any]],
    flights: list[dict[str, Any]],
    hotels: list[dict[str, Any]],
    request_id: str = "compose-test-1",
    llm_prompt_id: str | None = None,
    stays: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    trip_inner: dict[str, Any] = {
        "timezone": "UTC",
        "travelers": 1,
        "legs": legs,
    }
    if stays is not None:
        trip_inner["stays"] = stays
    sr: dict[str, Any] = {
        "output": {
            "trip": trip_inner,
            "budgets": {
                "flights": {"amount": 5000, "currency": "USD", "scope": "total_trip"},
                "hotels": {"amount": 500, "currency": "USD", "scope": "per_night"},
            },
            "confidence": 0.9,
        },
    }
    if llm_prompt_id:
        sr["prompt_id"] = llm_prompt_id
    out: dict[str, Any] = {
        "id": request_id,
        "structured_request": sr,
        "provider_response": {"flights": flights, "hotels": hotels},
    }
    if llm_prompt_id:
        out["prompt_id"] = llm_prompt_id
    return out


class ComposeTripTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        # Avoid cross-test pollution of FX cache (compose uses process-global cache).
        composer_module._USD_RATES_CACHE = None

    async def test_flight_only_two_leg_chain(self) -> None:
        """No hotels: connect flights A→B→C when edges and dates are valid."""
        payload = _structured_payload(
            legs=[
                {"from": "AAA", "to": "BBB", "depart_dates": ["2026-06-01"]},
                {"from": "BBB", "to": "CCC", "depart_dates": ["2026-06-02"]},
            ],
            flights=[
                _flight_group(
                    from_="AAA",
                    to="BBB",
                    depart_date="2026-06-01",
                    arrive_date="2026-06-01",
                    price="200",
                ),
                _flight_group(
                    from_="BBB",
                    to="CCC",
                    depart_date="2026-06-02",
                    arrive_date="2026-06-02",
                    price="150",
                ),
            ],
            hotels=[],
        )
        out = await compose_trip(payload, exchange_rate_latest_url="")
        its = out.get("trips", [])
        self.assertEqual(len(its), 1)
        it = its[0]
        self.assertEqual(len(it["flights"]), 2)
        self.assertEqual(it["flights"][0]["from"], "AAA")
        self.assertEqual(it["flights"][1]["to"], "CCC")
        self.assertEqual(it["hotels"], [])
        self.assertEqual(it["summary"]["trip_currency"], "USD")

    async def test_locations_dictionary_from_structured_request(self) -> None:
        """Leg from/to locations and stay city labels are copied onto each composed trip."""
        payload = _structured_payload(
            legs=[
                {
                    "from": "AAA",
                    "to": "BBB",
                    "depart_dates": ["2026-06-01"],
                    "from_location": "Alpha City",
                    "to_location": "Bravo City",
                },
                {
                    "from": "BBB",
                    "to": "CCC",
                    "depart_dates": ["2026-06-03"],
                    "from_location": "Bravo City",
                    "to_location": "Charlie City",
                },
            ],
            stays=[
                {"city_code": "BBB", "city": "Bravo Town", "duration": 2},
            ],
            flights=[
                _flight_group(
                    from_="AAA",
                    to="BBB",
                    depart_date="2026-06-01",
                    arrive_date="2026-06-01",
                ),
                _flight_group(
                    from_="BBB",
                    to="CCC",
                    depart_date="2026-06-03",
                    arrive_date="2026-06-03",
                ),
            ],
            hotels=[
                _hotel_group(
                    city_code="BBB",
                    check_in="2026-06-01",
                    check_out="2026-06-03",
                ),
            ],
        )
        out = await compose_trip(payload, exchange_rate_latest_url="")
        its = out.get("trips", [])
        self.assertEqual(len(its), 1)
        loc = its[0].get("locations_dictionary")
        self.assertEqual(
            loc,
            {
                "AAA": "Alpha City",
                "BBB": "Bravo Town",
                "CCC": "Charlie City",
            },
        )

    async def test_hybrid_flight_hotel_flight_single_stay(self) -> None:
        """Hotel at (city, arrival date): flight → hotel → next flight."""
        payload = _structured_payload(
            legs=[
                {"from": "AAA", "to": "BBB", "depart_dates": ["2026-06-01"]},
                {"from": "BBB", "to": "CCC", "depart_dates": ["2026-06-03"]},
            ],
            flights=[
                _flight_group(
                    from_="AAA",
                    to="BBB",
                    depart_date="2026-06-01",
                    arrive_date="2026-06-01",
                    price="100",
                ),
                _flight_group(
                    from_="BBB",
                    to="CCC",
                    depart_date="2026-06-03",
                    arrive_date="2026-06-03",
                    price="120",
                ),
            ],
            hotels=[
                _hotel_group(
                    city_code="BBB",
                    check_in="2026-06-01",
                    check_out="2026-06-03",
                    total="90",
                ),
            ],
        )
        out = await compose_trip(payload, exchange_rate_latest_url="")
        its = out["trips"]
        self.assertEqual(len(its), 1)
        it = its[0]
        self.assertEqual(len(it["flights"]), 2)
        self.assertEqual(len(it["hotels"]), 1)
        self.assertEqual(it["hotels"][0]["city_code"], "BBB")

    async def test_hybrid_gap_without_hotel_uses_flight_edge(self) -> None:
        """
        After a hotel stay, an intermediate stop with no hotel uses flight-only connection.
        A→B (hotel) → C → D: no hotel at C.
        """
        payload = _structured_payload(
            legs=[
                {"from": "AAA", "to": "BBB", "depart_dates": ["2026-06-01"]},
                {"from": "BBB", "to": "CCC", "depart_dates": ["2026-06-03"]},
                {"from": "CCC", "to": "DDD", "depart_dates": ["2026-06-04"]},
            ],
            flights=[
                _flight_group(
                    from_="AAA",
                    to="BBB",
                    depart_date="2026-06-01",
                    arrive_date="2026-06-01",
                    price="50",
                ),
                _flight_group(
                    from_="BBB",
                    to="CCC",
                    depart_date="2026-06-03",
                    arrive_date="2026-06-03",
                    price="60",
                ),
                _flight_group(
                    from_="CCC",
                    to="DDD",
                    depart_date="2026-06-04",
                    arrive_date="2026-06-04",
                    price="70",
                ),
            ],
            hotels=[
                _hotel_group(
                    city_code="BBB",
                    check_in="2026-06-01",
                    check_out="2026-06-03",
                    total="40",
                ),
            ],
            request_id="compose-test-hybrid-gap",
        )
        out = await compose_trip(payload, exchange_rate_latest_url="")
        its = out["trips"]
        self.assertEqual(len(its), 1)
        it = its[0]
        self.assertEqual(len(it["flights"]), 3)
        self.assertEqual(len(it["hotels"]), 1)
        self.assertEqual(it["flights"][2]["to"], "DDD")

    async def test_no_trips_when_flights_do_not_reach_destination(self) -> None:
        """Inventory ends at BBB but trip asks for CCC → no valid chain."""
        payload = _structured_payload(
            legs=[
                {"from": "AAA", "to": "CCC", "depart_dates": ["2026-06-01"]},
            ],
            flights=[
                _flight_group(
                    from_="AAA",
                    to="BBB",
                    depart_date="2026-06-01",
                    arrive_date="2026-06-01",
                ),
            ],
            hotels=[],
        )
        out = await compose_trip(payload, exchange_rate_latest_url="")
        self.assertEqual(out["trips"], [])

    async def test_no_trips_without_trip_endpoints(self) -> None:
        payload = {
            "id": "bad",
            "structured_request": {"output": {"trip": {"timezone": "UTC", "legs": []}}},
            "provider_response": {
                "flights": [
                    _flight_group(
                        from_="AAA",
                        to="BBB",
                        depart_date="2026-06-01",
                        arrive_date="2026-06-01",
                    )
                ],
                "hotels": [],
            },
        }
        out = await compose_trip(payload, exchange_rate_latest_url="")
        self.assertEqual(out["trips"], [])

    async def test_prompt_id_echoed_on_each_trip(self) -> None:
        payload = _structured_payload(
            legs=[
                {"from": "AAA", "to": "BBB", "depart_dates": ["2026-06-01"]},
                {"from": "BBB", "to": "CCC", "depart_dates": ["2026-06-02"]},
            ],
            flights=[
                _flight_group(
                    from_="AAA",
                    to="BBB",
                    depart_date="2026-06-01",
                    arrive_date="2026-06-01",
                ),
                _flight_group(
                    from_="BBB",
                    to="CCC",
                    depart_date="2026-06-02",
                    arrive_date="2026-06-02",
                ),
            ],
            hotels=[],
            llm_prompt_id="resp-openai-xyz",
        )
        out = await compose_trip(payload, exchange_rate_latest_url="")
        for it in out["trips"]:
            self.assertEqual(it.get("prompt_id"), "resp-openai-xyz")

    async def test_no_provider_response(self) -> None:
        out = await compose_trip({"id": "x"}, exchange_rate_latest_url="")
        self.assertEqual(out["trips"], [])

    async def test_multi_trip_round_trip_flight_only(self) -> None:
        """Full Amadeus offer with two trips: one flight group, no hotel."""
        legs = [
            {"from": "ZRH", "to": "LAX", "depart_dates": ["2026-06-01"]},
            {"from": "LAX", "to": "ZRH", "depart_dates": ["2026-06-15"]},
        ]
        rt_offer: dict[str, Any] = {
            "type": "flight-offer",
            "id": "rt-1",
            "price": {"currency": "USD", "grandTotal": "900", "total": "900"},
            "itineraries": [
                {
                    "segments": [
                        {
                            "departure": {"iataCode": "ZRH", "at": "2026-06-01T10:00:00"},
                            "arrival": {"iataCode": "LAX", "at": "2026-06-01T22:00:00"},
                        },
                    ],
                },
                {
                    "segments": [
                        {
                            "departure": {"iataCode": "LAX", "at": "2026-06-15T10:00:00"},
                            "arrival": {"iataCode": "ZRH", "at": "2026-06-15T22:00:00"},
                        },
                    ],
                },
            ],
        }
        payload = _structured_payload(
            legs=legs,
            flights=[
                {
                    "depart_date": "2026-06-01",
                    "arrive_date": "2026-06-15",
                    "from": "ZRH",
                    "to": "LAX",
                    "options": [rt_offer],
                },
            ],
            hotels=[],
        )
        out = await compose_trip(payload, exchange_rate_latest_url="")
        its = out["trips"]
        self.assertEqual(len(its), 1)
        self.assertEqual(len(its[0]["flights"]), 1)
        fg0 = its[0]["flights"][0]
        self.assertEqual(len(fg0["options"][0]["itineraries"]), 2)
        self.assertEqual(len(fg0["itinerary_legs"]), 2)
        self.assertEqual(
            set(fg0["itinerary_legs"][0].keys()),
            {"depart", "arrive", "from", "to"},
        )
        self.assertEqual(its[0]["hotels"], [])

    async def test_multi_trip_rt_hotel_between_trips(self) -> None:
        """
        Hotel stay between trip 1 and 2: itin1 last arrival date = check-in,
        itin2 first departure date = check-out (same city as gap endpoints).
        """
        legs = [
            {"from": "ZRH", "to": "LAX", "depart_dates": ["2026-06-01"]},
            {"from": "LAX", "to": "ZRH", "depart_dates": ["2026-06-15"]},
        ]
        rt_offer: dict[str, Any] = {
            "type": "flight-offer",
            "id": "rt-1",
            "price": {"currency": "USD", "grandTotal": "900", "total": "900"},
            "itineraries": [
                {
                    "segments": [
                        {
                            "departure": {"iataCode": "ZRH", "at": "2026-06-01T10:00:00"},
                            "arrival": {"iataCode": "LAX", "at": "2026-06-01T22:00:00"},
                        },
                    ],
                },
                {
                    "segments": [
                        {
                            "departure": {"iataCode": "LAX", "at": "2026-06-15T10:00:00"},
                            "arrival": {"iataCode": "ZRH", "at": "2026-06-15T22:00:00"},
                        },
                    ],
                },
            ],
        }
        payload = _structured_payload(
            legs=legs,
            flights=[
                {
                    "depart_date": "2026-06-01",
                    "arrive_date": "2026-06-15",
                    "from": "ZRH",
                    "to": "LAX",
                    "options": [rt_offer],
                },
            ],
            hotels=[
                _hotel_group(
                    city_code="LAX",
                    check_in="2026-06-01",
                    check_out="2026-06-15",
                    total="200",
                ),
            ],
        )
        out = await compose_trip(payload, exchange_rate_latest_url="")
        its = out["trips"]
        self.assertGreaterEqual(len(its), 1)
        matched = [it for it in its if len(it.get("hotels", [])) == 1 and len(it.get("flights", [])) == 1]
        self.assertEqual(len(matched), 1)
        it = matched[0]
        self.assertEqual(it["hotels"][0]["city_code"], "LAX")
        self.assertEqual(len(it["flights"][0]["options"][0]["itineraries"]), 2)
        self.assertEqual(len(it["flights"][0]["itinerary_legs"]), 2)

    async def test_multi_trip_london_metro_different_airports_hotel_lon(self) -> None:
        """
        Outbound arrives LCY, return departs LHR — hotel coded LON must still match the gap
        when check-in/out dates align with segment boundaries.
        airport_city_codes maps LCY→LON, LHR→LON so all three resolve to the same city.
        """
        legs = [
            {"from": "ZRH", "to": "LON", "depart_dates": ["2026-05-15"]},
            {"from": "LON", "to": "ZRH", "depart_dates": ["2026-05-18"]},
        ]
        rt_offer: dict[str, Any] = {
            "type": "flight-offer",
            "id": "rt-lon",
            "price": {"currency": "EUR", "grandTotal": "397.30", "total": "397.30"},
            "itineraries": [
                {
                    "segments": [
                        {
                            "departure": {"iataCode": "ZRH", "at": "2026-05-15T08:00:00"},
                            "arrival": {"iataCode": "LCY", "at": "2026-05-15T08:40:00"},
                        },
                    ],
                },
                {
                    "segments": [
                        {
                            "departure": {"iataCode": "LHR", "at": "2026-05-18T06:00:00"},
                            "arrival": {"iataCode": "ZRH", "at": "2026-05-18T08:40:00"},
                        },
                    ],
                },
            ],
        }
        payload = _structured_payload(
            legs=legs,
            flights=[
                {
                    "depart_date": "2026-05-15",
                    "arrive_date": "2026-05-18",
                    "from": "ZRH",
                    "to": "LON",
                    "options": [rt_offer],
                    "airport_city_codes": {
                        "ZRH": "ZRH",
                        "LCY": "LON",
                        "LHR": "LON",
                    },
                },
            ],
            hotels=[
                _hotel_group(
                    city_code="LON",
                    check_in="2026-05-15",
                    check_out="2026-05-18",
                    total="350",
                ),
            ],
        )
        out = await compose_trip(payload, exchange_rate_latest_url="")
        its = out["trips"]
        with_hotel = [it for it in its if len(it.get("hotels", [])) == 1]
        self.assertEqual(len(with_hotel), 1)
        self.assertEqual(with_hotel[0]["hotels"][0]["city_code"], "LON")


    async def test_multi_trip_three_itineraries_hotels_in_both_gaps(self) -> None:
        """
        Multi-city offer with 3 itineraries (ZRH→LAX, LAX→NYC, NYC→ZRH) produces
        2 gaps. Hotels in both gaps: LAX (gap 0) and NYC (gap 1).
        """
        legs = [
            {"from": "ZRH", "to": "LAX", "depart_dates": ["2026-07-01"]},
            {"from": "LAX", "to": "NYC", "depart_dates": ["2026-07-05"]},
            {"from": "NYC", "to": "ZRH", "depart_dates": ["2026-07-10"]},
        ]
        mc_offer: dict[str, Any] = {
            "type": "flight-offer",
            "id": "mc-1",
            "price": {"currency": "USD", "grandTotal": "1200", "total": "1200"},
            "itineraries": [
                {
                    "segments": [
                        {
                            "departure": {"iataCode": "ZRH", "at": "2026-07-01T08:00:00"},
                            "arrival": {"iataCode": "LAX", "at": "2026-07-01T18:00:00"},
                        },
                    ],
                },
                {
                    "segments": [
                        {
                            "departure": {"iataCode": "LAX", "at": "2026-07-05T09:00:00"},
                            "arrival": {"iataCode": "JFK", "at": "2026-07-05T17:00:00"},
                        },
                    ],
                },
                {
                    "segments": [
                        {
                            "departure": {"iataCode": "JFK", "at": "2026-07-10T20:00:00"},
                            "arrival": {"iataCode": "ZRH", "at": "2026-07-11T08:00:00"},
                        },
                    ],
                },
            ],
        }
        payload = _structured_payload(
            legs=legs,
            flights=[
                {
                    "depart_date": "2026-07-01",
                    "arrive_date": "2026-07-11",
                    "from": "ZRH",
                    "to": "ZRH",
                    "options": [mc_offer],
                    "airport_city_codes": {
                        "ZRH": "ZRH",
                        "LAX": "LAX",
                        "JFK": "NYC",
                    },
                },
            ],
            hotels=[
                _hotel_group(
                    city_code="LAX",
                    check_in="2026-07-01",
                    check_out="2026-07-05",
                    total="400",
                ),
                _hotel_group(
                    city_code="NYC",
                    check_in="2026-07-05",
                    check_out="2026-07-10",
                    total="500",
                ),
            ],
        )
        out = await compose_trip(payload, exchange_rate_latest_url="")
        its = out["trips"]
        with_hotels = [it for it in its if len(it.get("hotels", [])) == 2]
        self.assertEqual(len(with_hotels), 1)
        it = with_hotels[0]
        hotel_cities = [h["city_code"] for h in it["hotels"]]
        self.assertEqual(hotel_cities, ["LAX", "NYC"])
        self.assertEqual(len(it["flights"]), 1)
        fg = it["flights"][0]
        self.assertEqual(len(fg["itinerary_legs"]), 3)
        self.assertEqual(fg["itinerary_legs"][0]["from"], "ZRH")
        self.assertEqual(fg["itinerary_legs"][0]["to"], "LAX")
        self.assertEqual(fg["itinerary_legs"][1]["from"], "LAX")
        self.assertEqual(fg["itinerary_legs"][1]["to"], "JFK")
        self.assertEqual(fg["itinerary_legs"][2]["from"], "JFK")
        self.assertEqual(fg["itinerary_legs"][2]["to"], "ZRH")
        summary = it["summary"]
        self.assertEqual(summary["trip_start_date"], "2026-07-01")
        self.assertEqual(summary["trip_end_date"], "2026-07-11")
        self.assertEqual(summary["total_duration_days"], 10)

    async def test_multi_trip_three_itineraries_partial_hotel_no_trip(self) -> None:
        """
        3-itinerary offer but hotel only in gap 0 (not gap 1) — no trip with hotels
        should be produced (all gaps must be covered).
        """
        legs = [
            {"from": "ZRH", "to": "LAX", "depart_dates": ["2026-07-01"]},
            {"from": "LAX", "to": "NYC", "depart_dates": ["2026-07-05"]},
            {"from": "NYC", "to": "ZRH", "depart_dates": ["2026-07-10"]},
        ]
        mc_offer: dict[str, Any] = {
            "type": "flight-offer",
            "id": "mc-2",
            "price": {"currency": "USD", "grandTotal": "1200", "total": "1200"},
            "itineraries": [
                {
                    "segments": [
                        {
                            "departure": {"iataCode": "ZRH", "at": "2026-07-01T08:00:00"},
                            "arrival": {"iataCode": "LAX", "at": "2026-07-01T18:00:00"},
                        },
                    ],
                },
                {
                    "segments": [
                        {
                            "departure": {"iataCode": "LAX", "at": "2026-07-05T09:00:00"},
                            "arrival": {"iataCode": "JFK", "at": "2026-07-05T17:00:00"},
                        },
                    ],
                },
                {
                    "segments": [
                        {
                            "departure": {"iataCode": "JFK", "at": "2026-07-10T20:00:00"},
                            "arrival": {"iataCode": "ZRH", "at": "2026-07-11T08:00:00"},
                        },
                    ],
                },
            ],
        }
        payload = _structured_payload(
            legs=legs,
            flights=[
                {
                    "depart_date": "2026-07-01",
                    "arrive_date": "2026-07-11",
                    "from": "ZRH",
                    "to": "ZRH",
                    "options": [mc_offer],
                    "airport_city_codes": {
                        "ZRH": "ZRH",
                        "LAX": "LAX",
                        "JFK": "NYC",
                    },
                },
            ],
            hotels=[
                _hotel_group(
                    city_code="LAX",
                    check_in="2026-07-01",
                    check_out="2026-07-05",
                    total="400",
                ),
            ],
        )
        out = await compose_trip(payload, exchange_rate_latest_url="")
        its = out["trips"]
        with_hotels = [it for it in its if len(it.get("hotels", [])) >= 1]
        self.assertEqual(len(with_hotels), 0, "No trip should have hotels when not all gaps are covered")
        flight_only = [it for it in its if len(it.get("hotels", [])) == 0]
        self.assertEqual(len(flight_only), 1, "Flight-only trip should still be produced")


    async def test_trips_without_hotels_dropped_when_stays_present(self) -> None:
        """
        When the structured request has stays, flight-only trips must be
        dropped — only trips that include hotels survive.
        """
        payload = _structured_payload(
            legs=[
                {"from": "AAA", "to": "BBB", "depart_dates": ["2026-06-01"]},
                {"from": "BBB", "to": "CCC", "depart_dates": ["2026-06-02"]},
            ],
            stays=[
                {"city_code": "BBB", "city": "Bravo Town", "duration": 1},
            ],
            flights=[
                _flight_group(
                    from_="AAA",
                    to="BBB",
                    depart_date="2026-06-01",
                    arrive_date="2026-06-01",
                ),
                _flight_group(
                    from_="BBB",
                    to="CCC",
                    depart_date="2026-06-02",
                    arrive_date="2026-06-02",
                ),
            ],
            hotels=[],
        )
        out = await compose_trip(payload, exchange_rate_latest_url="")
        self.assertEqual(out["trips"], [], "Flight-only trips should be dropped when stays are present")

    async def test_trips_without_stays_keep_flight_only(self) -> None:
        """
        When the structured request has NO stays, flight-only trips are kept.
        """
        payload = _structured_payload(
            legs=[
                {"from": "AAA", "to": "BBB", "depart_dates": ["2026-06-01"]},
                {"from": "BBB", "to": "CCC", "depart_dates": ["2026-06-02"]},
            ],
            flights=[
                _flight_group(
                    from_="AAA",
                    to="BBB",
                    depart_date="2026-06-01",
                    arrive_date="2026-06-01",
                ),
                _flight_group(
                    from_="BBB",
                    to="CCC",
                    depart_date="2026-06-02",
                    arrive_date="2026-06-02",
                ),
            ],
            hotels=[],
        )
        out = await compose_trip(payload, exchange_rate_latest_url="")
        self.assertEqual(len(out["trips"]), 1)
        self.assertEqual(out["trips"][0]["hotels"], [])


if __name__ == "__main__":
    unittest.main()
