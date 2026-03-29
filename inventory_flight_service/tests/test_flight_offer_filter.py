import sys
import unittest
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_DIR / "src"
sys.path.insert(0, str(SRC_DIR))

from request_processor import (  # noqa: E402
    _filter_and_limit_flight_offers,
    _iso8601_duration_to_seconds,
    _offer_connection_count,
    _offer_total_duration_seconds,
)


def _seg() -> dict:
    return {
        "departure": {"iataCode": "AAA", "at": "2026-06-01T10:00:00"},
        "arrival": {"iataCode": "BBB", "at": "2026-06-01T12:00:00"},
    }


class FlightOfferFilterTest(unittest.TestCase):
    def test_iso8601_duration_parses_pt(self) -> None:
        self.assertEqual(_iso8601_duration_to_seconds("PT5H30M"), 5 * 3600 + 30 * 60)
        self.assertEqual(_iso8601_duration_to_seconds("PT2H"), 7200.0)

    def test_connection_count_sums_across_itineraries(self) -> None:
        one_stop = {
            "itineraries": [
                {
                    "duration": "PT3H",
                    "segments": [_seg(), _seg()],
                }
            ]
        }
        self.assertEqual(_offer_connection_count(one_stop), 1)
        direct = {
            "itineraries": [
                {"duration": "PT3H", "segments": [_seg()]},
                {"duration": "PT4H", "segments": [_seg(), _seg()]},
            ]
        }
        self.assertEqual(_offer_connection_count(direct), 1)

    def test_filter_sorts_by_connections_then_duration(self) -> None:
        two_hops = {
            "id": "slow-conn",
            "itineraries": [
                {
                    "duration": "PT5H",
                    "segments": [_seg(), _seg(), _seg()],
                }
            ],
        }
        long_direct = {
            "id": "long-direct",
            "itineraries": [{"duration": "PT10H", "segments": [_seg()]}],
        }
        short_direct = {
            "id": "short-direct",
            "itineraries": [{"duration": "PT8H", "segments": [_seg()]}],
        }
        resp = {
            "data": [two_hops, long_direct, short_direct],
            "meta": {"count": 3},
        }
        out = _filter_and_limit_flight_offers(resp, max_options=10)
        ids = [o["id"] for o in out["data"]]
        self.assertEqual(ids, ["short-direct", "long-direct", "slow-conn"])

    def test_filter_respects_max(self) -> None:
        offers = [
            {
                "id": f"o{i}",
                "itineraries": [{"duration": "PT1H", "segments": [_seg()]}],
            }
            for i in range(5)
        ]
        resp = {"data": offers}
        out = _filter_and_limit_flight_offers(resp, max_options=2)
        self.assertEqual(len(out["data"]), 2)

    def test_total_duration_sums_itineraries(self) -> None:
        offer = {
            "itineraries": [
                {"duration": "PT2H", "segments": [_seg()]},
                {"duration": "PT3H30M", "segments": [_seg()]},
            ]
        }
        self.assertEqual(_offer_total_duration_seconds(offer), 2 * 3600 + 3.5 * 3600)


if __name__ == "__main__":
    unittest.main()
