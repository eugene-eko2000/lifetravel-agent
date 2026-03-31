import sys
import unittest
from collections import defaultdict
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_DIR / "src"
sys.path.insert(0, str(SRC_DIR))

from request_processor import (  # noqa: E402
    _append_roundtrip_full_to_groups,
    _round_trip_outbound_return_segments,
    _tag_roundtrip_offer_full,
)


class RoundtripFullOfferTest(unittest.TestCase):
    def test_two_trips_outbound_return_segments(self) -> None:
        offer = {
            "itineraries": [
                {
                    "segments": [
                        {
                            "departure": {"iataCode": "ZRH", "at": "2026-06-01T10:00:00"},
                            "arrival": {"iataCode": "LAX", "at": "2026-06-01T22:00:00"},
                        }
                    ],
                },
                {
                    "segments": [
                        {
                            "departure": {"iataCode": "LAX", "at": "2026-06-15T10:00:00"},
                            "arrival": {"iataCode": "ZRH", "at": "2026-06-15T22:00:00"},
                        }
                    ],
                },
            ],
        }
        out, ret = _round_trip_outbound_return_segments(offer, return_from="LAX")
        assert out is not None and ret is not None
        self.assertEqual(len(out), 1)
        self.assertEqual(len(ret), 1)

    def test_single_trip_split_by_return_airport(self) -> None:
        offer = {
            "itineraries": [
                {
                    "segments": [
                        {
                            "departure": {"iataCode": "ZRH", "at": "2026-06-01T10:00:00"},
                            "arrival": {"iataCode": "LAX", "at": "2026-06-01T22:00:00"},
                        },
                        {
                            "departure": {"iataCode": "LAX", "at": "2026-06-10T10:00:00"},
                            "arrival": {"iataCode": "ZRH", "at": "2026-06-10T22:00:00"},
                        },
                    ],
                }
            ],
        }
        out, ret = _round_trip_outbound_return_segments(offer, return_from="LAX")
        assert out is not None and ret is not None
        self.assertEqual(len(out), 1)
        self.assertEqual(len(ret), 1)

    def test_full_offer_keeps_single_price_object(self) -> None:
        offer = {
            "id": "offer-1",
            "itineraries": [
                {
                    "segments": [
                        {
                            "departure": {"iataCode": "ZRH", "at": "2026-06-01T10:00:00"},
                            "arrival": {"iataCode": "LAX", "at": "2026-06-01T22:00:00"},
                        }
                    ],
                },
                {
                    "segments": [
                        {
                            "departure": {"iataCode": "LAX", "at": "2026-06-10T10:00:00"},
                            "arrival": {"iataCode": "ZRH", "at": "2026-06-10T22:00:00"},
                        }
                    ],
                },
            ],
            "price": {"grandTotal": "1000.00", "currency": "USD"},
        }
        _tag_roundtrip_offer_full(offer)
        self.assertEqual(offer["price"]["grandTotal"], "1000.00")
        self.assertEqual(offer["flight_kind"], "round_trip")

    def test_append_roundtrip_groups(self) -> None:
        gdict = defaultdict(list)
        dep: dict = {}
        arr: dict = {}
        meta: dict = {}
        opt = {
            "itineraries": [
                {
                    "segments": [
                        {
                            "departure": {"iataCode": "ZRH", "at": "2026-06-01T10:00:00"},
                            "arrival": {"iataCode": "LAX", "at": "2026-06-01T22:00:00"},
                        }
                    ],
                },
                {
                    "segments": [
                        {
                            "departure": {"iataCode": "LAX", "at": "2026-06-15T10:00:00"},
                            "arrival": {"iataCode": "ZRH", "at": "2026-06-15T22:00:00"},
                        }
                    ],
                },
            ],
        }
        _tag_roundtrip_offer_full(opt)
        _append_roundtrip_full_to_groups(
            gdict,
            dep,
            arr,
            meta,
            "ZRH",
            "LAX",
            "LAX",
            "ZRH",
            opt,
        )
        self.assertEqual(len(gdict), 1)
        self.assertIn("flight_kind", meta[list(gdict.keys())[0]])


if __name__ == "__main__":
    unittest.main()
