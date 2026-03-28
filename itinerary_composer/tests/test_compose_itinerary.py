"""
Integration-style unit tests for compose_itinerary: building itineraries from
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
from composer import compose_itinerary  # noqa: E402


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
) -> dict[str, Any]:
    return {
        "id": request_id,
        "structured_request": {
            "output": {
                "trip": {
                    "timezone": "UTC",
                    "travelers": 1,
                    "legs": legs,
                },
                "budgets": {
                    "flights": {"amount": 5000, "currency": "USD", "scope": "total_trip"},
                    "hotels": {"amount": 500, "currency": "USD", "scope": "per_night"},
                },
                "confidence": 0.9,
            },
        },
        "provider_response": {"flights": flights, "hotels": hotels},
    }


class ComposeItineraryTest(unittest.IsolatedAsyncioTestCase):
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
        out = await compose_itinerary(payload, exchange_rate_latest_url="")
        its = out.get("itineraries", [])
        self.assertEqual(len(its), 1)
        it = its[0]
        self.assertEqual(len(it["flights"]), 2)
        self.assertEqual(it["flights"][0]["from"], "AAA")
        self.assertEqual(it["flights"][1]["to"], "CCC")
        self.assertEqual(it["hotels"], [])
        self.assertEqual(it["summary"]["itinerary_currency"], "USD")

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
        out = await compose_itinerary(payload, exchange_rate_latest_url="")
        its = out["itineraries"]
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
        out = await compose_itinerary(payload, exchange_rate_latest_url="")
        its = out["itineraries"]
        self.assertEqual(len(its), 1)
        it = its[0]
        self.assertEqual(len(it["flights"]), 3)
        self.assertEqual(len(it["hotels"]), 1)
        self.assertEqual(it["flights"][2]["to"], "DDD")

    async def test_no_itineraries_when_flights_do_not_reach_destination(self) -> None:
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
        out = await compose_itinerary(payload, exchange_rate_latest_url="")
        self.assertEqual(out["itineraries"], [])

    async def test_no_itineraries_without_trip_endpoints(self) -> None:
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
        out = await compose_itinerary(payload, exchange_rate_latest_url="")
        self.assertEqual(out["itineraries"], [])

    async def test_no_provider_response(self) -> None:
        out = await compose_itinerary({"id": "x"}, exchange_rate_latest_url="")
        self.assertEqual(out["itineraries"], [])


if __name__ == "__main__":
    unittest.main()
