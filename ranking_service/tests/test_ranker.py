import sys
import unittest
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_DIR / "src"
sys.path.insert(0, str(SRC_DIR))

from ranker import rank_provider_response


def _flight_offer(
    price: float,
    duration_iso: str,
    dep_at: str,
    arr_at: str,
    carrier: str,
    segments: list[dict] | None = None,
) -> dict:
    segment_list = segments or [
        {
            "carrierCode": carrier,
            "departure": {"at": dep_at},
            "arrival": {"at": arr_at},
        }
    ]
    return {
        "id": "x",
        "type": "flight-offer",
        "source": "GDS",
        "price": {"grandTotal": str(price)},
        "itineraries": [
            {
                "duration": duration_iso,
                "segments": segment_list,
            }
        ],
    }


class RankerTest(unittest.TestCase):
    def test_rank_provider_response_ranks_flights_and_adds_meta(self) -> None:
        # Shape aligned with inventory_service/output -> flights[i]["data"][...]
        # Better option: cheaper, shorter, direct.
        offer_best = _flight_offer(
            price=300.0,
            duration_iso="PT4H",
            dep_at="2026-04-01T09:00:00",
            arr_at="2026-04-01T13:00:00",
            carrier="OS",
        )
        # Worse option: costlier, longer, one stop.
        offer_worse = _flight_offer(
            price=450.0,
            duration_iso="PT7H",
            dep_at="2026-04-01T10:00:00",
            arr_at="2026-04-01T17:00:00",
            carrier="CA",
            segments=[
                {
                    "carrierCode": "CA",
                    "departure": {"at": "2026-04-01T10:00:00"},
                    "arrival": {"at": "2026-04-01T12:00:00"},
                },
                {
                    "carrierCode": "CA",
                    "departure": {"at": "2026-04-01T13:30:00"},
                    "arrival": {"at": "2026-04-01T17:00:00"},
                },
            ],
        )

        payload = {
            "flights": [{"data": [offer_worse, offer_best]}],
            "hotels": {},
        }

        ranked = rank_provider_response(payload)

        self.assertIn("ranking_meta", ranked)
        self.assertEqual(ranked["ranking_meta"]["pipeline"], ["filter", "score", "re-rank", "diversify"])
        self.assertEqual(len(ranked["flights"]), 2)
        self.assertIn("_ranking", ranked["flights"][0])
        self.assertIn("_ranking", ranked["flights"][1])

        top_price = float(ranked["flights"][0]["price"]["grandTotal"])
        second_price = float(ranked["flights"][1]["price"]["grandTotal"])
        self.assertLessEqual(top_price, second_price)
        self.assertGreaterEqual(
            ranked["flights"][0]["_ranking"]["score"],
            ranked["flights"][1]["_ranking"]["score"],
        )

    def test_rank_provider_response_ranks_hotels_inventory_shape(self) -> None:
        # Shape aligned with inventory_service/output -> hotels[date][...]
        hotel_good = {
            "hotel": {
                "chainCode": "SI",
                "cityCode": "DEL",
                "hotelId": "SIDEL996",
                "latitude": 28.5263,
                "longitude": 77.21626,
                "name": "Sheraton New Delhi Hotel",
                "type": "hotel",
                "distance": {"value": 1.2},
                "rating": "4.6",
            },
            "available": True,
            "offers": [
                {
                    "id": "FP2KHQ2K0D",
                    "checkInDate": "2026-04-19",
                    "checkOutDate": "2026-04-24",
                    "price": {"currency": "INR", "total": "88500.00"},
                    "policies": {
                        "refundable": {
                            "cancellationRefund": "REFUNDABLE_UP_TO_DEADLINE"
                        }
                    },
                }
            ],
        }
        hotel_bad = {
            "hotel": {
                "chainCode": "GI",
                "cityCode": "DEL",
                "hotelId": "GIDEL110",
                "distance": {"value": 6.0},
                "type": "hotel",
                "rating": "3.8",
            },
            "available": True,
            "offers": [
                {
                    "id": "QOR5YE3411",
                    "checkInDate": "2026-04-19",
                    "checkOutDate": "2026-04-24",
                    "price": {"currency": "INR", "total": "63189.00"},
                    "policies": {"refundable": {"cancellationRefund": "NON_REFUNDABLE"}},
                }
            ],
        }

        payload = {
            "flights": [],
            "hotels": {
                "2026-04-19": [hotel_bad, hotel_good],
            },
        }

        ranked = rank_provider_response(payload)
        ranked_hotels = ranked["hotels"]["2026-04-19"]

        self.assertEqual(len(ranked_hotels), 2)
        self.assertIn("_ranking", ranked_hotels[0])
        self.assertIn("_ranking", ranked_hotels[1])

        # Better rated + closer option should rank ahead here.
        self.assertEqual(ranked_hotels[0]["hotel"]["hotelId"], "SIDEL996")

    def test_rank_provider_response_handles_malformed_input(self) -> None:
        ranked = rank_provider_response({"flights": "bad", "hotels": "bad"})
        self.assertEqual(ranked["flights"], [])
        self.assertEqual(ranked["hotels"], {})


if __name__ == "__main__":
    unittest.main()
