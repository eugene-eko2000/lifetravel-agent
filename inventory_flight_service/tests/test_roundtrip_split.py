import sys
import unittest
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_DIR / "src"
sys.path.insert(0, str(SRC_DIR))

from request_processor import _split_roundtrip_offer_to_legs  # noqa: E402


class RoundtripOfferSplitTest(unittest.TestCase):
    def test_two_itineraries_halves_price(self) -> None:
        offer = {
            "id": "offer-1",
            "itineraries": [
                {
                    "segments": [
                        {
                            "departure": {"at": "2026-06-01T10:00:00"},
                            "arrival": {"at": "2026-06-01T22:00:00"},
                        }
                    ],
                },
                {
                    "segments": [
                        {
                            "departure": {"at": "2026-06-10T10:00:00"},
                            "arrival": {"at": "2026-06-10T22:00:00"},
                        }
                    ],
                },
            ],
            "price": {"grandTotal": "1000.00", "currency": "USD"},
        }
        out, ret = _split_roundtrip_offer_to_legs(offer, return_from="LAX")
        self.assertIsNotNone(out)
        self.assertIsNotNone(ret)
        assert out is not None and ret is not None
        self.assertEqual(len(out["itineraries"]), 1)
        self.assertEqual(len(ret["itineraries"]), 1)
        self.assertEqual(out["price"]["grandTotal"], "500.00")
        self.assertEqual(ret["price"]["grandTotal"], "500.00")

    def test_single_itinerary_splits_on_return_airport(self) -> None:
        offer = {
            "id": "offer-2",
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
            "price": {"grandTotal": "800", "currency": "USD"},
        }
        out, ret = _split_roundtrip_offer_to_legs(offer, return_from="LAX")
        self.assertIsNotNone(out)
        self.assertIsNotNone(ret)
        assert out is not None and ret is not None
        self.assertEqual(len(out["itineraries"][0]["segments"]), 1)
        self.assertEqual(len(ret["itineraries"][0]["segments"]), 1)


if __name__ == "__main__":
    unittest.main()
