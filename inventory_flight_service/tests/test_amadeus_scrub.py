"""Tests for Amadeus flight response scrubbing."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from amadeus_scrub import scrub_flight_dictionaries, scrub_flight_offer  # noqa: E402


class TestAmadeusScrubFlight(unittest.TestCase):
    def test_scrub_offer_strips_unknown_top_level(self) -> None:
        raw = {
            "id": "off1",
            "source": "GDS",
            "itineraries": [],
            "price": {"currency": "EUR", "grandTotal": "100.00", "fees": [{"x": 1}]},
            "travelerPricings": [],
            "instantTicketingRequired": True,
        }
        out = scrub_flight_offer(raw)
        self.assertEqual(out["id"], "off1")
        self.assertNotIn("source", out)
        self.assertNotIn("instantTicketingRequired", out)
        self.assertNotIn("fees", out["price"])

    def test_scrub_segment_endpoints(self) -> None:
        raw = {
            "id": "x",
            "itineraries": [
                {
                    "duration": "PT2H",
                    "segments": [
                        {
                            "id": "s1",
                            "carrierCode": "LX",
                            "number": "123",
                            "departure": {
                                "iataCode": "ZRH",
                                "at": "2026-05-01T10:00:00",
                                "extra": "drop",
                            },
                            "arrival": {"iataCode": "LHR", "at": "2026-05-01T11:00:00"},
                        }
                    ],
                }
            ],
        }
        out = scrub_flight_offer(raw)
        dep = out["itineraries"][0]["segments"][0]["departure"]
        self.assertNotIn("extra", dep)
        self.assertEqual(dep["iataCode"], "ZRH")

    def test_scrub_dictionaries(self) -> None:
        d = {
            "locations": {
                "ZRH": {"cityCode": "ZRH", "countryCode": "CH", "name": "Zurich Airport"},
            },
            "carriers": {"LX": "Swiss", "U2": "easyJet"},
            "aircraft": {"32N": "A320neo"},
        }
        out = scrub_flight_dictionaries(d)
        self.assertNotIn("aircraft", out)
        self.assertNotIn("name", out["locations"]["ZRH"])
        self.assertEqual(out["locations"]["ZRH"]["cityCode"], "ZRH")
        self.assertEqual(out["carriers"]["LX"], "Swiss")


if __name__ == "__main__":
    unittest.main()
