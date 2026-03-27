import sys
import unittest
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_DIR / "src"
sys.path.insert(0, str(SRC_DIR))

from cfg import Cfg
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
                {"from": "Zurich", "to": "Beijing", "depart_dates": ["2026-03-12"]},
                {"from": "Beijing", "to": "Hong Kong", "depart_dates": ["2026-03-15"]},
                {"from": "Hong Kong", "to": "Singapore", "depart_dates": ["2026-03-17"]},
                {"from": "Singapore", "to": "New Delhi", "depart_dates": ["2026-03-19"]},
                {"from": "New Delhi", "to": "Zurich", "depart_dates": ["2026-03-24"]},
            ],
            "stays": [
                {
                    "city": "Beijing",
                    "city_code": "BEJ",
                    "check_in": "2026-03-12",
                    "check_out": "2026-03-15",
                    "min_rooms": 1,
                },
                {
                    "city": "Hong Kong",
                    "city_code": "HKG",
                    "check_in": "2026-03-15",
                    "check_out": "2026-03-17",
                    "min_rooms": 1,
                },
                {
                    "city": "Singapore",
                    "city_code": "SIN",
                    "check_in": "2026-03-17",
                    "check_out": "2026-03-19",
                    "min_rooms": 1,
                },
                {
                    "city": "New Delhi",
                    "city_code": "DEL",
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
        cfg = Cfg.from_env()
        translated = translate_trip_request_to_amadeus_requests(SOURCE_EXAMPLE["output"], cfg)

        self.assertEqual(len(translated), 5)
        for i, item in enumerate(translated, start=1):
            self.assertEqual(item["type"], "flight")
            self.assertEqual(item["method"], "POST")
            self.assertEqual(item["leg_index"], i)

        flight_payload = translated[0]["payload"]
        self.assertEqual(len(flight_payload["originDestinations"]), 1)
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
            translated[-1]["payload"]["originDestinations"][0]["departureDateTimeRange"][
                "date"
            ],
            "2026-03-24",
        )
        self.assertEqual(len(flight_payload["travelers"]), 1)
        self.assertEqual(flight_payload["travelers"][0]["travelerType"], "ADULT")
        self.assertEqual(flight_payload["sources"], ["GDS"])
        self.assertEqual(flight_payload["searchCriteria"]["maxFlightOffers"], 10)


class RoundTripTranslatorTest(unittest.TestCase):
    def test_consecutive_reverse_legs_use_single_roundtrip_request(self) -> None:
        cfg = Cfg.from_env()
        trip = {
            "trip": {
                "travelers": 1,
                "legs": [
                    {"from": "ZRH", "to": "LAX", "depart_dates": ["2026-06-01"]},
                    {"from": "LAX", "to": "ZRH", "depart_dates": ["2026-06-10"]},
                ],
            },
        }
        translated = translate_trip_request_to_amadeus_requests(trip, cfg)
        self.assertEqual(len(translated), 1)
        item = translated[0]
        self.assertEqual(item["type"], "flight_roundtrip")
        self.assertEqual(item["leg_index_out"], 1)
        self.assertEqual(item["leg_index_return"], 2)
        self.assertEqual(item["outbound_date"], "2026-06-01")
        self.assertEqual(item["return_date"], "2026-06-10")
        ods = item["payload"]["originDestinations"]
        self.assertEqual(len(ods), 2)
        self.assertEqual(ods[0]["id"], "1")
        self.assertEqual(ods[0]["originLocationCode"], "ZRH")
        self.assertEqual(ods[0]["destinationLocationCode"], "LAX")
        self.assertEqual(ods[0]["departureDateTimeRange"]["date"], "2026-06-01")
        self.assertEqual(ods[1]["id"], "2")
        self.assertEqual(ods[1]["originLocationCode"], "LAX")
        self.assertEqual(ods[1]["destinationLocationCode"], "ZRH")
        self.assertEqual(ods[1]["departureDateTimeRange"]["date"], "2026-06-10")

    def test_roundtrip_date_cartesian_emits_multiple_requests(self) -> None:
        cfg = Cfg.from_env()
        trip = {
            "trip": {
                "travelers": 1,
                "legs": [
                    {"from": "A", "to": "B", "depart_dates": ["2026-01-01", "2026-01-02"]},
                    {"from": "B", "to": "A", "depart_dates": ["2026-01-10"]},
                ],
            },
        }
        translated = translate_trip_request_to_amadeus_requests(trip, cfg)
        self.assertEqual(len(translated), 2)
        self.assertTrue(all(t["type"] == "flight_roundtrip" for t in translated))


class AirlinePreferencesTranslatorTest(unittest.TestCase):
    def test_included_carrier_codes_on_one_way_requests(self) -> None:
        cfg = Cfg.from_env()
        trip = {
            "trip": {
                "travelers": 1,
                "airline_preferences": ["lh", "LX", "LH"],
                "legs": [
                    {"from": "ZRH", "to": "LHR", "depart_dates": ["2026-06-01"]},
                ],
            },
        }
        translated = translate_trip_request_to_amadeus_requests(trip, cfg)
        self.assertEqual(len(translated), 1)
        sc = translated[0]["payload"]["searchCriteria"]
        self.assertEqual(sc["maxFlightOffers"], 10)
        self.assertIn("flightFilters", sc)
        cr = sc["flightFilters"]["carrierRestrictions"]
        self.assertEqual(cr["includedCarrierCodes"], ["LH", "LX"])

    def test_roundtrip_includes_carrier_restrictions(self) -> None:
        cfg = Cfg.from_env()
        trip = {
            "trip": {
                "travelers": 1,
                "airline_preferences": ["QR"],
                "legs": [
                    {"from": "ZRH", "to": "DOH", "depart_dates": ["2026-06-01"]},
                    {"from": "DOH", "to": "ZRH", "depart_dates": ["2026-06-10"]},
                ],
            },
        }
        translated = translate_trip_request_to_amadeus_requests(trip, cfg)
        self.assertEqual(len(translated), 1)
        sc = translated[0]["payload"]["searchCriteria"]
        self.assertEqual(
            sc["flightFilters"]["carrierRestrictions"]["includedCarrierCodes"],
            ["QR"],
        )


if __name__ == "__main__":
    unittest.main()
