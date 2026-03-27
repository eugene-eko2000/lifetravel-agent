import sys
import unittest
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_DIR / "src"
sys.path.insert(0, str(SRC_DIR))

from composer import _annotate_itinerary_flight_hotel_prices  # noqa: E402


class CurrencyAnnotationTest(unittest.TestCase):
    def test_flight_price_fields_get_itinerary_currency_duplicates(self) -> None:
        usd_rates = {"USD": 1.0, "EUR": 1.0, "CHF": 1.1}
        itin = {
            "flights": [
                {
                    "options": [
                        {
                            "price": {
                                "currency": "EUR",
                                "grandTotal": "200.00",
                                "total": "200.00",
                                "base": "100.00",
                                "fees": [{"amount": "10.00", "type": "X"}],
                            }
                        }
                    ]
                }
            ],
            "hotels": [],
        }
        _annotate_itinerary_flight_hotel_prices(itin, "CHF", usd_rates)
        p = itin["flights"][0]["options"][0]["price"]
        self.assertIn("grandTotal_itinerary_currency", p)
        self.assertIn("total_itinerary_currency", p)
        self.assertIn("base_itinerary_currency", p)
        self.assertEqual(p["fees"][0]["amount_itinerary_currency"], "11.00")

    def test_compute_summary_uses_single_itinerary_currency(self) -> None:
        from composer import _compute_summary  # noqa: E402

        usd_rates = {"USD": 1.0, "EUR": 1.0, "CHF": 2.0}
        itin = {
            "flights": [
                {
                    "depart_date": "2026-01-01",
                    "arrive_date": "2026-01-02",
                    "from": "A",
                    "to": "B",
                    "options": [
                        {
                            "price": {
                                "currency": "EUR",
                                "grandTotal": "50.00",
                            }
                        }
                    ],
                }
            ],
            "hotels": [],
        }
        summary = _compute_summary(itin, "CHF", usd_rates)
        self.assertEqual(summary["itinerary_currency"], "CHF")
        self.assertEqual(summary["total_flights_cost"], 100.0)
        self.assertEqual(summary["itinerary_start_date"], "2026-01-01")
        self.assertEqual(summary["itinerary_end_date"], "2026-01-02")
        self.assertEqual(summary["total_duration_days"], 1)


if __name__ == "__main__":
    unittest.main()
