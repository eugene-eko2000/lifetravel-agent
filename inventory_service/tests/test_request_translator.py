import sys
import unittest
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_DIR / "src"
sys.path.insert(0, str(SRC_DIR))

from request_translator import translate_trip_request_to_amadeus_requests


SOURCE_EXAMPLE = {
    "request_id": "af373e1f-facb-43c9-8610-72d6590b5b1e",
    "prompt_id": "resp_0217114b348040340069a610cfe714819694063b7bfc0d7042",
    "type": "valid_request",
    "output": {
        "trip": {
            "timezone": "Europe/Zurich",
            "travelers": 1,
            "legs": [
                {"from": "Zurich", "to": "Beijing", "depart_date": "2026-03-12"},
                {"from": "Beijing", "to": "Hong Kong", "depart_date": "2026-03-15"},
                {"from": "Hong Kong", "to": "Singapore", "depart_date": "2026-03-17"},
                {"from": "Singapore", "to": "New Delhi", "depart_date": "2026-03-19"},
                {"from": "New Delhi", "to": "Zurich", "depart_date": "2026-03-24"},
            ],
            "stays": [
                {
                    "city": "Beijing",
                    "check_in": "2026-03-12",
                    "check_out": "2026-03-15",
                    "min_rooms": 1,
                },
                {
                    "city": "Hong Kong",
                    "check_in": "2026-03-15",
                    "check_out": "2026-03-17",
                    "min_rooms": 1,
                },
                {
                    "city": "Singapore",
                    "check_in": "2026-03-17",
                    "check_out": "2026-03-19",
                    "min_rooms": 1,
                },
                {
                    "city": "New Delhi",
                    "check_in": "2026-03-19",
                    "check_out": "2026-03-24",
                    "min_rooms": 1,
                },
            ],
        },
        "budgets": {
            "flights": {"amount": 3000, "currency": "CHF", "scope": "total_trip"},
            "hotels": {"amount": 300, "currency": "CHF", "scope": "per_night"},
        },
        "assumptions": [
            "Interpreted '12.03.2026' as 2026-03-12 (dd.mm.yyyy).",
            "Assumed the number of travelers is 1 since it was not specified.",
        ],
        "missing_fields": [
            "Number of travelers (needed to correctly interpret 'per person' hotel budget)."
        ],
        "confidence": 0.86,
    },
}


class RequestTranslatorTest(unittest.TestCase):
    def test_translate_trip_request_to_amadeus_requests(self) -> None:
        translated = translate_trip_request_to_amadeus_requests(SOURCE_EXAMPLE["output"])

        self.assertEqual(len(translated), 5)
        self.assertEqual(translated[0]["type"], "flight")
        self.assertEqual(translated[0]["method"], "POST")
        self.assertEqual(translated[1]["type"], "hotel")
        self.assertEqual(translated[1]["method"], "GET")

        flight_payload = translated[0]["payload"]
        self.assertEqual(len(flight_payload["originDestinations"]), 5)
        self.assertEqual(flight_payload["originDestinations"][0]["id"], "1")
        self.assertEqual(
            flight_payload["originDestinations"][0]["originLocationCode"], "ZURICH"
        )
        self.assertEqual(
            flight_payload["originDestinations"][0]["destinationLocationCode"], "BEIJING"
        )
        self.assertEqual(
            flight_payload["originDestinations"][0]["departureDateTimeRange"]["date"],
            "2026-03-12",
        )
        self.assertEqual(
            flight_payload["originDestinations"][-1]["departureDateTimeRange"]["date"],
            "2026-03-24",
        )
        self.assertEqual(len(flight_payload["travelers"]), 1)
        self.assertEqual(flight_payload["travelers"][0]["travelerType"], "ADULT")
        self.assertEqual(flight_payload["sources"], ["GDS"])
        self.assertEqual(flight_payload["searchCriteria"]["maxFlightOffers"], 10)

        hotel_requests = translated[1:]
        self.assertEqual(len(hotel_requests), 4)

        first_hotel_query = hotel_requests[0]["query_params"]
        self.assertEqual(first_hotel_query["cityCode"], "BEI")
        self.assertEqual(first_hotel_query["radius"], 20)
        self.assertEqual(first_hotel_query["radiusUnit"], "KM")
        self.assertEqual(first_hotel_query["hotelSource"], "ALL")


if __name__ == "__main__":
    unittest.main()
