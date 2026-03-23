import sys
import unittest
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_DIR / "src"
sys.path.insert(0, str(SRC_DIR))

from ranker import _normalize, rank_provider_response, rank_single_itinerary


INPUT_PROVIDER_RESPONSE = {
    "flights": [
        {
            "data": [
                {
                    "id": "1",
                    "type": "flight-offer",
                    "source": "GDS",
                    "price": {"grandTotal": "300.00"},
                    "pricingOptions": {"refundableFare": True},
                    "itineraries": [
                        {
                            "duration": "PT4H",
                            "segments": [
                                {
                                    "carrierCode": "OS",
                                    "departure": {"at": "2026-04-19T09:00:00"},
                                    "arrival": {"at": "2026-04-19T13:00:00"},
                                }
                            ],
                        }
                    ],
                }
            ]
        },
        {
            "data": [
                {
                    "id": "2",
                    "type": "flight-offer",
                    "source": "GDS",
                    "price": {"grandTotal": "420.00"},
                    "pricingOptions": {"includedCheckedBagsOnly": True},
                    "itineraries": [
                        {
                            "duration": "PT5H20M",
                            "segments": [
                                {
                                    "carrierCode": "CA",
                                    "departure": {"at": "2026-04-19T10:20:00"},
                                    "arrival": {"at": "2026-04-19T15:40:00"},
                                }
                            ],
                        }
                    ],
                },
                {
                    "id": "3",
                    "type": "flight-offer",
                    "source": "GDS",
                    "price": {"grandTotal": "690.00"},
                    "itineraries": [
                        {
                            "duration": "PT9H30M",
                            "segments": [
                                {
                                    "carrierCode": "SQ",
                                    "departure": {"at": "2026-04-19T01:15:00"},
                                    "arrival": {"at": "2026-04-19T04:15:00"},
                                },
                                {
                                    "carrierCode": "SQ",
                                    "departure": {"at": "2026-04-19T05:00:00"},
                                    "arrival": {"at": "2026-04-19T10:45:00"},
                                },
                            ],
                        }
                    ],
                },
            ]
        }
    ],
    "hotels": {
        "2026-04-19": [
            {
                "available": True,
                "hotel": {
                    "chainCode": "SI",
                    "cityCode": "DEL",
                    "hotelId": "SIDEL996",
                    "distance": {"value": 1.2},
                    "type": "hotel",
                    "rating": "4.6",
                },
                "offers": [
                    {
                        "id": "FP2KHQ2K0D",
                        "checkInDate": "2026-04-19",
                        "checkOutDate": "2026-04-21",
                        "price": {"currency": "INR", "total": "260.00"},
                        "policies": {"cancellation": {"type": "PARTIAL_STAY"}},
                    }
                ],
            },
            {
                "available": True,
                "hotel": {
                    "chainCode": "GI",
                    "cityCode": "DEL",
                    "hotelId": "GIDEL110",
                    "distance": {"value": 3.8},
                    "type": "hotel",
                    "rating": "4.2",
                },
                "offers": [
                    {
                        "id": "QOR5YE3411",
                        "checkInDate": "2026-04-19",
                        "checkOutDate": "2026-04-21",
                        "price": {"currency": "INR", "total": "220.00"},
                        "policies": {"cancellation": {"type": "FULL_STAY"}},
                    }
                ],
            },
            {
                "available": True,
                "hotel": {
                    "chainCode": "HX",
                    "cityCode": "DEL",
                    "hotelId": "HXDEL777",
                    "distance": {"value": 6.1},
                    "type": "hotel",
                    "rating": "3.8",
                },
                "offers": [
                    {
                        "id": "HXDEL77701",
                        "checkInDate": "2026-04-19",
                        "checkOutDate": "2026-04-21",
                        "price": {"currency": "INR", "total": "180.00"},
                        "policies": {"cancellation": {"type": "FULL_STAY"}},
                    }
                ],
            },
        ],
        "2026-04-21": [
            {
                "available": True,
                "hotel": {
                    "chainCode": "SI",
                    "cityCode": "SIN",
                    "hotelId": "SISIN101",
                    "distance": {"value": 1.0},
                    "type": "hotel",
                    "rating": "4.8",
                },
                "offers": [
                    {
                        "id": "SISIN10101",
                        "checkInDate": "2026-04-21",
                        "checkOutDate": "2026-04-23",
                        "price": {"currency": "SGD", "total": "300.00"},
                        "policies": {"cancellation": {"type": "PARTIAL_STAY"}},
                    }
                ],
            },
            {
                "available": True,
                "hotel": {
                    "chainCode": "BX",
                    "cityCode": "SIN",
                    "hotelId": "BXSIN202",
                    "distance": {"value": 4.4},
                    "type": "hotel",
                    "rating": "4.1",
                },
                "offers": [
                    {
                        "id": "BXSIN20201",
                        "checkInDate": "2026-04-21",
                        "checkOutDate": "2026-04-23",
                        "price": {"currency": "SGD", "total": "190.00"},
                        "policies": {"cancellation": {"type": "FULL_STAY"}},
                    }
                ],
            },
        ],
    },
}


GOLDEN_RANKED_PROVIDER_RESPONSE = {
    "flights": [
        {
            "_ranking": {
                "duration_minutes": 240.0,
                "eligible": True,
                "ineligibility_reason": "",
                "price": 300.0,
                "score": 100.0,
                "stops": 0,
            },
            "id": "1",
            "type": "flight-offer",
            "source": "GDS",
            "price": {"grandTotal": "300.00"},
            "pricingOptions": {"refundableFare": True},
            "itineraries": [
                {
                    "duration": "PT4H",
                    "segments": [
                        {
                            "carrierCode": "OS",
                            "departure": {"at": "2026-04-19T09:00:00"},
                            "arrival": {"at": "2026-04-19T13:00:00"},
                        }
                    ],
                }
            ],
        },
        {
            "_ranking": {
                "duration_minutes": 320.0,
                "eligible": True,
                "ineligibility_reason": "",
                "price": 420.0,
                "score": 85.71,
                "stops": 0,
            },
            "id": "2",
            "type": "flight-offer",
            "source": "GDS",
            "price": {"grandTotal": "420.00"},
            "pricingOptions": {"includedCheckedBagsOnly": True},
            "itineraries": [
                {
                    "duration": "PT5H20M",
                    "segments": [
                        {
                            "carrierCode": "CA",
                            "departure": {"at": "2026-04-19T10:20:00"},
                            "arrival": {"at": "2026-04-19T15:40:00"},
                        }
                    ],
                }
            ],
        },
        {
            "_ranking": {
                "duration_minutes": 570.0,
                "eligible": True,
                "ineligibility_reason": "",
                "price": 690.0,
                "score": 13.25,
                "stops": 1,
            },
            "id": "3",
            "type": "flight-offer",
            "source": "GDS",
            "price": {"grandTotal": "690.00"},
            "itineraries": [
                {
                    "duration": "PT9H30M",
                    "segments": [
                        {
                            "carrierCode": "SQ",
                            "departure": {"at": "2026-04-19T01:15:00"},
                            "arrival": {"at": "2026-04-19T04:15:00"},
                        },
                        {
                            "carrierCode": "SQ",
                            "departure": {"at": "2026-04-19T05:00:00"},
                            "arrival": {"at": "2026-04-19T10:45:00"},
                        },
                    ],
                }
            ],
        },
    ],
    "hotels": {
        "2026-04-19": [
            {
                "_ranking": {
                    "eligible": True,
                    "ineligibility_reason": "",
                    "price_per_night": 130.0,
                    "score": 55.0,
                },
                "available": True,
                "hotel": {
                    "chainCode": "SI",
                    "cityCode": "DEL",
                    "hotelId": "SIDEL996",
                    "distance": {"value": 1.2},
                    "type": "hotel",
                    "rating": "4.6",
                },
                "offers": [
                    {
                        "id": "FP2KHQ2K0D",
                        "checkInDate": "2026-04-19",
                        "checkOutDate": "2026-04-21",
                        "price": {"currency": "INR", "total": "260.00"},
                        "policies": {"cancellation": {"type": "PARTIAL_STAY"}},
                    }
                ],
            },
            {
                "_ranking": {
                    "eligible": True,
                    "ineligibility_reason": "",
                    "price_per_night": 110.0,
                    "score": 36.89,
                },
                "available": True,
                "hotel": {
                    "chainCode": "GI",
                    "cityCode": "DEL",
                    "hotelId": "GIDEL110",
                    "distance": {"value": 3.8},
                    "type": "hotel",
                    "rating": "4.2",
                },
                "offers": [
                    {
                        "id": "QOR5YE3411",
                        "checkInDate": "2026-04-19",
                        "checkOutDate": "2026-04-21",
                        "price": {"currency": "INR", "total": "220.00"},
                        "policies": {"cancellation": {"type": "FULL_STAY"}},
                    }
                ],
            },
            {
                "_ranking": {
                    "eligible": True,
                    "ineligibility_reason": "",
                    "price_per_night": 90.0,
                    "score": 35.0,
                },
                "available": True,
                "hotel": {
                    "chainCode": "HX",
                    "cityCode": "DEL",
                    "hotelId": "HXDEL777",
                    "distance": {"value": 6.1},
                    "type": "hotel",
                    "rating": "3.8",
                },
                "offers": [
                    {
                        "id": "HXDEL77701",
                        "checkInDate": "2026-04-19",
                        "checkOutDate": "2026-04-21",
                        "price": {"currency": "INR", "total": "180.00"},
                        "policies": {"cancellation": {"type": "FULL_STAY"}},
                    }
                ],
            },
        ],
        "2026-04-21": [
            {
                "_ranking": {
                    "eligible": True,
                    "ineligibility_reason": "",
                    "price_per_night": 150.0,
                    "score": 55.0,
                },
                "available": True,
                "hotel": {
                    "chainCode": "SI",
                    "cityCode": "SIN",
                    "hotelId": "SISIN101",
                    "distance": {"value": 1.0},
                    "type": "hotel",
                    "rating": "4.8",
                },
                "offers": [
                    {
                        "id": "SISIN10101",
                        "checkInDate": "2026-04-21",
                        "checkOutDate": "2026-04-23",
                        "price": {"currency": "SGD", "total": "300.00"},
                        "policies": {"cancellation": {"type": "PARTIAL_STAY"}},
                    }
                ],
            },
            {
                "_ranking": {
                    "eligible": True,
                    "ineligibility_reason": "",
                    "price_per_night": 95.0,
                    "score": 35.0,
                },
                "available": True,
                "hotel": {
                    "chainCode": "BX",
                    "cityCode": "SIN",
                    "hotelId": "BXSIN202",
                    "distance": {"value": 4.4},
                    "type": "hotel",
                    "rating": "4.1",
                },
                "offers": [
                    {
                        "id": "BXSIN20201",
                        "checkInDate": "2026-04-21",
                        "checkOutDate": "2026-04-23",
                        "price": {"currency": "SGD", "total": "190.00"},
                        "policies": {"cancellation": {"type": "FULL_STAY"}},
                    }
                ],
            },
        ],
    },
    "ranking_meta": {
        "pipeline": ["score", "annotate_only"],
        "flight_count_in": 3,
        "flight_count_out": 3,
        "hotel_dates_out": 2,
    },
}


class RankerTest(unittest.TestCase):
    def test_normalize_with_several_values(self) -> None:
        values = [10.0, 20.0, 30.0, 50.0]

        higher = _normalize(values, higher_better=True)
        lower = _normalize(values, higher_better=False)

        expected_higher = [0.0, 0.25, 0.5, 1.0]
        expected_lower = [1.0, 0.75, 0.5, 0.0]

        for got, exp in zip(higher, expected_higher):
            self.assertAlmostEqual(got, exp, places=6)
        for got, exp in zip(lower, expected_lower):
            self.assertAlmostEqual(got, exp, places=6)

    def test_normalize_with_equal_values(self) -> None:
        values = [7.0, 7.0, 7.0]

        higher = _normalize(values, higher_better=True)
        lower = _normalize(values, higher_better=False)

        # With zero range, denominator falls back to EPS, so all norms are 0.
        self.assertEqual(higher, [0.0, 0.0, 0.0])
        self.assertEqual(lower, [0.0, 0.0, 0.0])

    def test_rank_provider_response_matches_golden_output(self) -> None:
        ranked = rank_provider_response(INPUT_PROVIDER_RESPONSE)
        self.assertEqual(ranked, GOLDEN_RANKED_PROVIDER_RESPONSE)

    def test_rank_provider_response_handles_malformed_input(self) -> None:
        ranked = rank_provider_response({"flights": "bad", "hotels": "bad"})
        self.assertEqual(ranked["flights"], [])
        self.assertEqual(ranked["hotels"], {})

    def test_rank_single_itinerary_with_grouped_format(self) -> None:
        flight_group_vie_del = {
            "depart_date": "2026-04-19",
            "arrive_date": "2026-04-19",
            "from": "VIE",
            "to": "DEL",
            "options": INPUT_PROVIDER_RESPONSE["flights"][0]["data"]
            + INPUT_PROVIDER_RESPONSE["flights"][1]["data"],
        }
        flight_group_del_sin = {
            "depart_date": "2026-04-21",
            "arrive_date": "2026-04-21",
            "from": "DEL",
            "to": "SIN",
            "options": INPUT_PROVIDER_RESPONSE["flights"][0]["data"],
        }
        hotel_group_del = {
            "city_code": "DEL",
            "check_in": "2026-04-19",
            "check_out": "2026-04-21",
            "options": INPUT_PROVIDER_RESPONSE["hotels"]["2026-04-19"],
        }
        hotel_group_sin = {
            "city_code": "SIN",
            "check_in": "2026-04-21",
            "check_out": "2026-04-23",
            "options": INPUT_PROVIDER_RESPONSE["hotels"]["2026-04-21"],
        }
        itinerary = {
            "flights": [flight_group_vie_del, flight_group_del_sin],
            "hotels": [hotel_group_del, hotel_group_sin],
        }

        ranked = rank_single_itinerary(itinerary)
        self.assertIn("flights", ranked)
        self.assertIn("hotels", ranked)
        self.assertEqual(len(ranked["flights"]), 2)
        self.assertEqual(len(ranked["hotels"]), 2)

        for fg in ranked["flights"]:
            self.assertIn("options", fg)
            self.assertIn("depart_date", fg)
            self.assertIn("arrive_date", fg)
            self.assertIn("from", fg)
            self.assertIn("to", fg)
            for opt in fg["options"]:
                self.assertIn("_ranking", opt)

        for hg in ranked["hotels"]:
            self.assertIn("options", hg)
            self.assertIn("city_code", hg)
            self.assertIn("check_in", hg)
            self.assertIn("check_out", hg)
            for opt in hg["options"]:
                self.assertIn("_ranking", opt)

    def test_rank_single_itinerary_empty(self) -> None:
        ranked = rank_single_itinerary({"flights": [], "hotels": []})
        self.assertEqual(ranked["flights"], [])
        self.assertEqual(ranked["hotels"], [])

    def test_rank_single_itinerary_options_sorted_by_score(self) -> None:
        flight_group = {
            "depart_date": "2026-04-19",
            "arrive_date": "2026-04-19",
            "from": "VIE",
            "to": "DEL",
            "options": INPUT_PROVIDER_RESPONSE["flights"][0]["data"]
            + INPUT_PROVIDER_RESPONSE["flights"][1]["data"],
        }
        itinerary = {"flights": [flight_group], "hotels": []}
        ranked = rank_single_itinerary(itinerary)
        options = ranked["flights"][0]["options"]
        option_scores = [opt["_ranking"]["score"] for opt in options]
        self.assertEqual(option_scores, sorted(option_scores, reverse=True))


if __name__ == "__main__":
    unittest.main()
