import sys
import unittest
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_DIR / "src"
sys.path.insert(0, str(SRC_DIR))

from ranker import (
    _clamp,
    _flight_price,
    _hotel_total_price,
    _normalize,
    _rank_flights,
    _rank_hotels_for_date,
    rank_provider_response,
    rank_single_trip,
)


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
                        "price": {
                            "currency": "INR",
                            "total": "260.00",
                            "total_trip_currency": "260.00",
                        },
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
                        "price": {
                            "currency": "INR",
                            "total": "220.00",
                            "total_trip_currency": "220.00",
                        },
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
                        "price": {
                            "currency": "INR",
                            "total": "180.00",
                            "total_trip_currency": "180.00",
                        },
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
                        "price": {
                            "currency": "SGD",
                            "total": "300.00",
                            "total_trip_currency": "300.00",
                        },
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
                        "price": {
                            "currency": "SGD",
                            "total": "190.00",
                            "total_trip_currency": "190.00",
                        },
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
    "flight_dictionaries": {},
    "locations_dictionary": {},
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
                        "price": {
                            "currency": "INR",
                            "total": "260.00",
                            "total_trip_currency": "260.00",
                        },
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
                        "price": {
                            "currency": "INR",
                            "total": "220.00",
                            "total_trip_currency": "220.00",
                        },
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
                        "price": {
                            "currency": "INR",
                            "total": "180.00",
                            "total_trip_currency": "180.00",
                        },
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
                        "price": {
                            "currency": "SGD",
                            "total": "300.00",
                            "total_trip_currency": "300.00",
                        },
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
                        "price": {
                            "currency": "SGD",
                            "total": "190.00",
                            "total_trip_currency": "190.00",
                        },
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

    def test_normalize_all_nonfinite_returns_neutral(self) -> None:
        """When every value is inf/nan, min/max are undefined; use neutral 1.0 per slot."""
        self.assertEqual(_normalize([float("inf")] * 3, higher_better=False), [1.0, 1.0, 1.0])

    def test_clamp_nonfinite_returns_lo(self) -> None:
        """Python's min(hi, nan) can return hi; never treat NaN as in-range."""
        self.assertEqual(_clamp(float("nan"), 0.0, 100.0), 0.0)

    def test_hotel_ranking_varies_by_price_when_distance_missing(self) -> None:
        """Missing distance is +inf for all; must not collapse scores to 100 via NaN clamp bug."""
        offers = [
            {
                "available": True,
                "hotel": {"rating": "4.0"},
                "offers": [
                    {
                        "checkInDate": "2026-04-19",
                        "checkOutDate": "2026-04-21",
                        "price": {"total": "100.00"},
                    }
                ],
            },
            {
                "available": True,
                "hotel": {"rating": "4.0"},
                "offers": [
                    {
                        "checkInDate": "2026-04-19",
                        "checkOutDate": "2026-04-21",
                        "price": {"total": "500.00"},
                    }
                ],
            },
        ]
        ranked = _rank_hotels_for_date(offers, {})
        scores = [o["_ranking"]["score"] for o in ranked]
        self.assertEqual(len(scores), 2)
        self.assertNotEqual(scores[0], scores[1])
        self.assertNotEqual(scores[0], 100.0)
        self.assertNotEqual(scores[1], 100.0)

    def test_rank_provider_response_matches_golden_output(self) -> None:
        ranked = rank_provider_response(INPUT_PROVIDER_RESPONSE)
        self.assertEqual(ranked, GOLDEN_RANKED_PROVIDER_RESPONSE)

    def test_rank_provider_response_handles_malformed_input(self) -> None:
        ranked = rank_provider_response({"flights": "bad", "hotels": "bad"})
        self.assertEqual(ranked["flights"], [])
        self.assertEqual(ranked["flight_dictionaries"], {})
        self.assertEqual(ranked["locations_dictionary"], {})
        self.assertEqual(ranked["hotels"], {})

    def test_rank_single_trip_with_grouped_format(self) -> None:
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
        trip = {
            "flights": [flight_group_vie_del, flight_group_del_sin],
            "hotels": [hotel_group_del, hotel_group_sin],
        }

        ranked = rank_single_trip(trip)
        self.assertIn("flights", ranked)
        self.assertIn("hotels", ranked)
        self.assertEqual(ranked["flight_dictionaries"], {})
        self.assertEqual(ranked["locations_dictionary"], {})
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

        # Flight group 0: same three options as INPUT golden → same scores as GOLDEN flights.
        fg0 = ranked["flights"][0]["options"]
        self.assertEqual(
            [(o["id"], o["_ranking"]["score"]) for o in fg0],
            [("1", 100.0), ("2", 85.71), ("3", 13.25)],
        )
        # Flight group 1: single option; normalization is over a cohort of one (fixed score).
        fg1 = ranked["flights"][1]["options"]
        self.assertEqual(len(fg1), 1)
        self.assertEqual(fg1[0]["id"], "1")
        self.assertEqual(fg1[0]["_ranking"]["score"], 40.0)

        hg_del = ranked["hotels"][0]["options"]
        self.assertEqual(
            [o["_ranking"]["score"] for o in hg_del],
            [55.0, 36.89, 35.0],
        )
        hg_sin = ranked["hotels"][1]["options"]
        self.assertEqual([o["_ranking"]["score"] for o in hg_sin], [55.0, 35.0])

    def test_rank_single_trip_passes_through_amadeus_dictionaries(self) -> None:
        dicts = {"carriers": {"LX": "SWISS"}, "locations": {"ZRH": {"cityCode": "ZRH"}}}
        ranked = rank_single_trip(
            {
                "flights": [],
                "hotels": [],
                "flight_dictionaries": dicts,
            }
        )
        self.assertEqual(ranked["flight_dictionaries"], dicts)
        self.assertEqual(ranked["locations_dictionary"], {})

    def test_rank_single_trip_passes_through_locations_dictionary(self) -> None:
        locs = {"ZRH": "Zurich", "del": "New Delhi"}
        ranked = rank_single_trip(
            {
                "flights": [],
                "hotels": [],
                "locations_dictionary": locs,
            }
        )
        self.assertEqual(ranked["locations_dictionary"], {"ZRH": "Zurich", "DEL": "New Delhi"})

    def test_rank_single_trip_empty(self) -> None:
        ranked = rank_single_trip({"flights": [], "hotels": []})
        self.assertEqual(ranked["flights"], [])
        self.assertEqual(ranked["flight_dictionaries"], {})
        self.assertEqual(ranked["locations_dictionary"], {})
        self.assertEqual(ranked["hotels"], [])

    def test_rank_single_trip_passes_through_prompt_id(self) -> None:
        ranked = rank_single_trip(
            {
                "trip_id": "550e8400-e29b-41d4-a716-446655440000",
                "prompt_id": "resp-abc",
                "flights": [],
                "hotels": [],
            }
        )
        self.assertEqual(ranked.get("prompt_id"), "resp-abc")

    def test_flight_price_prefers_trip_currency_fields(self) -> None:
        offer = {
            "price": {
                "grandTotal": "1000.00",
                "grandTotal_trip_currency": "250.00",
            },
            "itineraries": [{"duration": "PT4H", "segments": []}],
        }
        self.assertEqual(_flight_price(offer), 250.0)

    def test_hotel_total_price_prefers_total_trip_currency(self) -> None:
        offer = {
            "offers": [
                {
                    "checkInDate": "2026-04-19",
                    "checkOutDate": "2026-04-21",
                    "price": {
                        "currency": "INR",
                        "total": "999.00",
                        "total_trip_currency": "40.00",
                    },
                }
            ],
            "hotel": {"distance": {"value": 1.0}, "rating": "4.0"},
        }
        self.assertEqual(_hotel_total_price(offer), 40.0)

    def test_rank_single_trip_uses_trip_currency_for_scoring(self) -> None:
        """When *_trip_currency is present, ranking score uses those amounts."""
        cheap_in_ic = {
            "id": "cheap-ic",
            "type": "flight-offer",
            "price": {
                "grandTotal": "999.00",
                "grandTotal_trip_currency": "100.00",
            },
            "itineraries": [
                {
                    "duration": "PT4H",
                    "segments": [
                        {
                            "carrierCode": "XX",
                            "departure": {"at": "2026-04-19T09:00:00"},
                            "arrival": {"at": "2026-04-19T13:00:00"},
                        }
                    ],
                }
            ],
        }
        expensive_in_ic = {
            "id": "expensive-ic",
            "type": "flight-offer",
            "price": {
                "grandTotal": "100.00",
                "grandTotal_trip_currency": "500.00",
            },
            "itineraries": [
                {
                    "duration": "PT4H",
                    "segments": [
                        {
                            "carrierCode": "YY",
                            "departure": {"at": "2026-04-19T09:00:00"},
                            "arrival": {"at": "2026-04-19T13:00:00"},
                        }
                    ],
                }
            ],
        }
        trip = {
            "trip_currency": "CHF",
            "summary": {"trip_currency": "CHF"},
            "flights": [
                {
                    "depart_date": "2026-04-19",
                    "arrive_date": "2026-04-19",
                    "from": "VIE",
                    "to": "DEL",
                    "options": [expensive_in_ic, cheap_in_ic],
                }
            ],
            "hotels": [],
        }
        ranked = rank_single_trip(trip)
        opts = ranked["flights"][0]["options"]
        self.assertEqual(opts[0]["id"], "cheap-ic")
        self.assertEqual(opts[0]["_ranking"]["price"], 100.0)
        self.assertEqual(opts[0]["_ranking"]["currency"], "CHF")
        self.assertEqual(opts[0]["_ranking"]["score"], 66.0)
        self.assertEqual(opts[1]["_ranking"]["score"], 36.0)

    def test_rank_single_trip_hotel_uses_trip_currency_for_scoring(self) -> None:
        """When total_trip_currency is present, hotel PPN uses that (not raw total)."""
        cheap_in_ic = {
            "available": True,
            "hotel": {
                "hotelId": "cheap-h",
                "distance": {"value": 2.0},
                "rating": "4.0",
            },
            "offers": [
                {
                    "id": "o-cheap",
                    "checkInDate": "2026-04-19",
                    "checkOutDate": "2026-04-21",
                    "price": {
                        "currency": "INR",
                        "total": "900.00",
                        "total_trip_currency": "100.00",
                    },
                }
            ],
        }
        expensive_in_ic = {
            "available": True,
            "hotel": {
                "hotelId": "expensive-h",
                "distance": {"value": 2.0},
                "rating": "4.0",
            },
            "offers": [
                {
                    "id": "o-exp",
                    "checkInDate": "2026-04-19",
                    "checkOutDate": "2026-04-21",
                    "price": {
                        "currency": "INR",
                        "total": "100.00",
                        "total_trip_currency": "400.00",
                    },
                }
            ],
        }
        trip = {
            "trip_currency": "CHF",
            "summary": {"trip_currency": "CHF"},
            "flights": [],
            "hotels": [
                {
                    "city_code": "DEL",
                    "check_in": "2026-04-19",
                    "check_out": "2026-04-21",
                    "options": [expensive_in_ic, cheap_in_ic],
                }
            ],
        }
        ranked = rank_single_trip(trip)
        opts = ranked["hotels"][0]["options"]
        self.assertEqual(opts[0]["offers"][0]["id"], "o-cheap")
        self.assertEqual(opts[0]["_ranking"]["price_per_night"], 50.0)
        self.assertEqual(opts[0]["_ranking"]["currency"], "CHF")
        self.assertEqual(opts[0]["_ranking"]["score"], 35.0)
        self.assertEqual(opts[1]["_ranking"]["score"], 0.0)

    def test_rank_single_trip_options_sorted_by_score(self) -> None:
        flight_group = {
            "depart_date": "2026-04-19",
            "arrive_date": "2026-04-19",
            "from": "VIE",
            "to": "DEL",
            "options": INPUT_PROVIDER_RESPONSE["flights"][0]["data"]
            + INPUT_PROVIDER_RESPONSE["flights"][1]["data"],
        }
        trip = {"flights": [flight_group], "hotels": []}
        ranked = rank_single_trip(trip)
        options = ranked["flights"][0]["options"]
        option_scores = [opt["_ranking"]["score"] for opt in options]
        self.assertEqual(option_scores, sorted(option_scores, reverse=True))
        self.assertEqual(option_scores, [100.0, 85.71, 13.25])

    def test_rank_single_trip_truncates_options_using_flights_and_hotels_number(self) -> None:
        flight_group = {
            "depart_date": "2026-04-19",
            "arrive_date": "2026-04-19",
            "from": "VIE",
            "to": "DEL",
            "options": INPUT_PROVIDER_RESPONSE["flights"][0]["data"]
            + INPUT_PROVIDER_RESPONSE["flights"][1]["data"],
        }
        hotel_group = {
            "city_code": "DEL",
            "check_in": "2026-04-19",
            "check_out": "2026-04-21",
            "options": INPUT_PROVIDER_RESPONSE["hotels"]["2026-04-19"],
        }
        trip = {
            "flights": [flight_group],
            "hotels": [hotel_group],
        }
        structured_request = {
            "output": {
                "flights_number": 1,
                "hotels_number": 2,
            },
        }
        ranked = rank_single_trip(trip, structured_request=structured_request)
        self.assertEqual(len(ranked["flights"][0]["options"]), 1)
        self.assertEqual(len(ranked["hotels"][0]["options"]), 2)

    def _flight_offer_with_segment_bags(
        self,
        offer_id: str,
        bag_quantities: list[int],
        *,
        cabin: str = "ECONOMY",
        carrier: str = "LH",
    ) -> dict:
        segments: list[dict] = []
        fare_rows: list[dict] = []
        for i, qty in enumerate(bag_quantities):
            sid = f"{offer_id}-seg-{i}"
            segments.append(
                {
                    "id": sid,
                    "carrierCode": carrier,
                    "departure": {"at": "2026-04-19T09:00:00"},
                    "arrival": {"at": "2026-04-19T13:00:00"},
                }
            )
            fare_rows.append(
                {
                    "segmentId": sid,
                    "cabin": cabin,
                    "includedCheckedBags": {"quantity": qty},
                }
            )
        return {
            "id": offer_id,
            "type": "flight-offer",
            "price": {"grandTotal": "300.00"},
            "pricingOptions": {"refundableFare": True},
            "itineraries": [{"duration": "PT4H", "segments": segments}],
            "travelerPricings": [{"fareDetailsBySegment": fare_rows}],
        }

    def test_baggage_preference_penalizes_per_segment_mismatch(self) -> None:
        good = self._flight_offer_with_segment_bags("good", [2, 2])
        bad = self._flight_offer_with_segment_bags("bad", [0, 2])
        flight_group = {
            "depart_date": "2026-04-19",
            "arrive_date": "2026-04-19",
            "from": "VIE",
            "to": "DEL",
            "options": [bad, good],
        }
        trip = {
            "baggage_preference": {"num_checked_bags": 2},
            "flights": [flight_group],
            "hotels": [],
        }
        ranked = rank_single_trip(trip)
        opts = ranked["flights"][0]["options"]
        self.assertEqual(opts[0]["id"], "good")
        self.assertGreater(opts[0]["_ranking"]["score"], opts[1]["_ranking"]["score"])

    def test_cabin_and_airline_preferences_boost_matching_offers(self) -> None:
        eco = self._flight_offer_with_segment_bags("eco", [1], cabin="ECONOMY", carrier="LH")
        biz = self._flight_offer_with_segment_bags("biz", [1], cabin="BUSINESS", carrier="LX")
        flight_group = {
            "depart_date": "2026-04-19",
            "arrive_date": "2026-04-19",
            "from": "VIE",
            "to": "DEL",
            "options": [biz, eco],
        }
        trip = {
            "cabin_preferences": ["economy"],
            "airline_preferences": ["LH"],
            "flights": [flight_group],
            "hotels": [],
        }
        ranked = rank_single_trip(trip)
        opts = ranked["flights"][0]["options"]
        self.assertEqual(opts[0]["id"], "eco")
        self.assertGreater(opts[0]["_ranking"]["score"], opts[1]["_ranking"]["score"])

    def test_flight_preferences_merge_from_nested_trip(self) -> None:
        good = self._flight_offer_with_segment_bags("g2", [2])
        bad = self._flight_offer_with_segment_bags("b2", [0])
        flight_group = {
            "depart_date": "2026-04-19",
            "arrive_date": "2026-04-19",
            "from": "VIE",
            "to": "DEL",
            "options": [bad, good],
        }
        trip = {
            "trip": {"baggage_preference": {"num_checked_bags": 2}},
            "flights": [flight_group],
            "hotels": [],
        }
        ranked = rank_single_trip(trip)
        opts = ranked["flights"][0]["options"]
        self.assertEqual(opts[0]["id"], "g2")

    def test_rank_flights_accepts_baggage_via_constraints_dict(self) -> None:
        a = self._flight_offer_with_segment_bags("a", [2])
        b = self._flight_offer_with_segment_bags("b", [0])
        ranked = _rank_flights(
            [{"data": [b, a]}],
            {"baggage_preference": {"num_checked_bags": 2}},
        )
        self.assertEqual(ranked[0]["id"], "a")


if __name__ == "__main__":
    unittest.main()
