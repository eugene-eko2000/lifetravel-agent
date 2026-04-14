"""Tests for Amadeus hotel response scrubbing."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from amadeus_scrub import scrub_flight_dictionaries, scrub_hotel_offer  # noqa: E402


class TestAmadeusScrubHotel(unittest.TestCase):
    def test_scrub_hotel_offer_strips_noise(self) -> None:
        raw = {
            "available": True,
            "self": "https://api.example/hotels/xyz",
            "hotel": {
                "hotelId": "ADPAR001",
                "name": "Test Inn",
                "latitude": 48.85,
                "longitude": 2.35,
                "rating": 4.2,
                "amenities": ["WIFI"],
                "media": [{"uri": "http://img"}],
                "distance": {"value": 1.2, "unit": "KM"},
            },
            "offers": [
                {
                    "checkInDate": "2026-06-01",
                    "checkOutDate": "2026-06-03",
                    "price": {
                        "currency": "EUR",
                        "total": "200",
                        "variations": {
                            "average": {"total": "100", "markup": "5"},
                        },
                    },
                    "policies": {
                        "paymentType": "DEPOSIT",
                        "refundable": {"cancellationRefund": "FULL_STAY"},
                    },
                }
            ],
        }
        out = scrub_hotel_offer(raw)
        self.assertNotIn("self", out)
        self.assertNotIn("media", out["hotel"])
        self.assertEqual(out["hotel"]["distance"], {"value": 1.2})
        avg = out["offers"][0]["price"]["variations"]["average"]
        self.assertNotIn("markup", avg)
        self.assertEqual(avg["total"], "100")

    def test_scrub_flight_dictionaries_passthrough(self) -> None:
        d = scrub_flight_dictionaries(
            {"locations": {"ZRH": {"cityCode": "ZRH", "detailedName": "Zurich"}}, "meta": {}}
        )
        self.assertNotIn("meta", d)
        self.assertNotIn("detailedName", d["locations"]["ZRH"])


if __name__ == "__main__":
    unittest.main()
