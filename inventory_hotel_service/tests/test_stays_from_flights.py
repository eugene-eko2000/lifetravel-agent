"""Tests for stay construction from flight groups (multi-trip round-trips)."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from request_processor import _build_stays_from_flight_groups  # noqa: E402


def _round_trip_zrh_lon_fixture() -> dict:
    """Group-level dates/to are misleading; gap is in segment trip0 last / trip1 first."""
    return {
        "flight_kind": "round_trip",
        "from": "ZRH",
        "to": "LON",
        "depart_date": "2026-05-12",
        "arrive_date": "2026-05-18",
        "options": [
            {
                "itineraries": [
                    {
                        "segments": [
                            {
                                "departure": {
                                    "iataCode": "ZRH",
                                    "at": "2026-05-12T10:00:00",
                                },
                                "arrival": {
                                    "iataCode": "LCY",
                                    "at": "2026-05-12T11:00:00",
                                },
                            }
                        ]
                    },
                    {
                        "segments": [
                            {
                                "departure": {
                                    "iataCode": "LHR",
                                    "at": "2026-05-18T14:00:00",
                                },
                                "arrival": {
                                    "iataCode": "ZRH",
                                    "at": "2026-05-18T17:00:00",
                                },
                            }
                        ]
                    },
                ]
            }
        ],
    }


_LON_ROUND_TRIP_LEGS = [
    {"from": "ZRH", "to": "LON"},
    {"from": "LON", "to": "ZRH"},
]


class TestBuildStaysFromFlights(unittest.TestCase):
    def test_multi_trip_round_trip_london_metro(self) -> None:
        fg = _round_trip_zrh_lon_fixture()
        stays = [{"city_code": "LON", "duration": 0, "min_rooms": 1}]
        trip = {"legs": _LON_ROUND_TRIP_LEGS}
        built = _build_stays_from_flight_groups(
            [fg], stays, currency="CHF", travelers=2, trip=trip
        )
        self.assertTrue(built, "expected at least one built stay for LON from LCY/LHR gap")
        self.assertTrue(any(s["city_code"] == "LON" for s in built))
        pair = next(s for s in built if s["city_code"] == "LON")
        self.assertEqual(pair["check_in"], "2026-05-12")
        self.assertEqual(pair["check_out"], "2026-05-18")

    def test_coarse_group_dates_alone_would_not_pair_lon(self) -> None:
        """Without multi-trip extraction, group arrive_date is return to ZRH — no LON stay."""
        fg = {
            "from": "ZRH",
            "to": "LON",
            "depart_date": "2026-05-12",
            "arrive_date": "2026-05-18",
            "options": [],
        }
        stays = [{"city_code": "LON", "duration": 0, "min_rooms": 1}]
        trip = {"legs": _LON_ROUND_TRIP_LEGS}
        built = _build_stays_from_flight_groups(
            [fg], stays, currency="CHF", travelers=1, trip=trip
        )
        self.assertEqual(built, [])


if __name__ == "__main__":
    unittest.main()
