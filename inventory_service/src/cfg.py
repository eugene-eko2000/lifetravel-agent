import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Cfg:
    endpoint_port: int
    amqp_host: str
    amqp_port: str
    amqp_user: str
    amqp_password: str
    rabbitmq_exchange: str
    rabbitmq_subscribe_routing_key: str
    rabbitmq_queue_name: str
    amadeus_flights_offers_url: str
    amadeus_hotels_list_url: str
    amadeus_hotels_list_by_geocode_url: str
    amadeus_hotels_offers_url: str
    amadeus_hotels_offers_limit: int
    amadeus_hotels_citycode_radius_km: int
    amadeus_hotels_latlng_radius_km: int
    amadeus_auth_token: str

    @classmethod
    def from_env(cls) -> "Cfg":
        return cls(
            endpoint_port=int(os.getenv("PORT", "8080")),
            amqp_host=os.getenv("AMQP_HOST", "localhost"),
            amqp_port=os.getenv("AMQP_PORT", "5672"),
            amqp_user=os.getenv("AMQP_USER", "guest"),
            amqp_password=os.getenv("AMQP_PASSWORD", "guest"),
            rabbitmq_exchange=os.getenv("RABBITMQ_EXCHANGE", "lifetravel_agent"),
            rabbitmq_subscribe_routing_key=os.getenv(
                "RABBITMQ_SUBSCRIBE_ROUTING_KEY",
                "itinerary:query_router_response",
            ),
            rabbitmq_queue_name=os.getenv(
                "RABBITMQ_QUEUE_NAME",
                "inventory_service_structured_request_queue",
            ),
            amadeus_flights_offers_url=os.getenv(
                "AMADEUS_FLIGHTS_OFFERS_URL",
                "https://test.api.amadeus.com/v2/shopping/flight-offers",
            ),
            amadeus_hotels_list_url=os.getenv(
                "AMADEUS_HOTELS_LIST_URL",
                "https://test.api.amadeus.com/v1/reference-data/locations/hotels/by-city",
            ),
            amadeus_hotels_list_by_geocode_url=os.getenv(
                "AMADEUS_HOTELS_LIST_BY_GEOCODE_URL",
                "https://test.api.amadeus.com/v1/reference-data/locations/hotels/by-geocode",
            ),
            amadeus_hotels_offers_url=os.getenv(
                "AMADEUS_HOTELS_OFFERS_URL",
                "https://test.api.amadeus.com/v3/shopping/hotel-offers",
            ),
            amadeus_hotels_offers_limit=int(
                os.getenv("AMADEUS_HOTELS_OFFERS_LIMIT", "10")
            ),
            amadeus_hotels_citycode_radius_km=int(
                os.getenv("AMADEUS_HOTELS_CITYCODE_RADIUS_KM", "15")
            ),
            amadeus_hotels_latlng_radius_km=int(
                os.getenv("AMADEUS_HOTELS_LATLNG_RADIUS_KM", "5")
            ),
            amadeus_auth_token=os.getenv("AMADEUS_AUTH_TOKEN", ""),
        )

    @property
    def amqp_url(self) -> str:
        return (
            f"amqp://{self.amqp_user}:"
            f"{self.amqp_password}@{self.amqp_host}:{self.amqp_port}/"
        )
