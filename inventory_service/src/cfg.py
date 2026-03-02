import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Cfg:
    endpoint_port: int
    amadeus_flights_offers_url: str
    amadeus_hotels_list_url: str
    amadeus_hotels_offers_url: str

    @classmethod
    def from_env(cls) -> "Cfg":
        return cls(
            endpoint_port=int(os.getenv("PORT", "8080")),
            amadeus_flights_offers_url=os.getenv(
                "AMADEUS_FLIGHTS_OFFERS_URL",
                "https://test.api.amadeus.com/v2/shopping/flight-offers",
            ),
            amadeus_hotels_list_url=os.getenv(
                "AMADEUS_HOTELS_LIST_URL",
                "https://test.api.amadeus.com/v1/reference-data/locations/hotels/by-city",
            ),
            amadeus_hotels_offers_url=os.getenv(
                "AMADEUS_HOTELS_OFFERS_URL",
                "https://test.api.amadeus.com/v3/shopping/hotel-offers",
            ),
        )
