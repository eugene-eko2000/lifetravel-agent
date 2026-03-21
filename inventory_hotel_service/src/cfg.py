import os
from dataclasses import dataclass


def _parse_amadeus_max_hotel_offers() -> int | None:
    """Max number of hotel-ID offer-query chunks; unset or empty => unlimited."""
    raw = os.getenv("AMADEUS_MAX_HOTEL_OFFERS", "").strip()
    if not raw:
        return None
    try:
        return max(0, int(raw))
    except ValueError:
        return None


@dataclass(frozen=True)
class Cfg:
    endpoint_port: int
    amqp_host: str
    amqp_port: str
    amqp_user: str
    amqp_password: str
    rabbitmq_exchange: str
    rabbitmq_subscribe_routing_key: str
    rabbitmq_publish_routing_key: str
    rabbitmq_debug_routing_key: str
    rabbitmq_status_routing_key: str
    rabbitmq_queue_name: str
    amadeus_hotels_list_url: str
    amadeus_hotels_list_by_geocode_url: str
    amadeus_hotels_offers_url: str
    amadeus_hotels_qps_limit: float | None
    amadeus_429_max_attempts: int
    amadeus_token_url: str
    amadeus_hotels_offers_limit: int
    amadeus_max_hotel_offers: int | None
    amadeus_hotels_citycode_radius_km: int
    amadeus_hotels_latlng_radius_km: int
    amadeus_client_id: str
    amadeus_client_secret: str

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
                "itinerary:verified_response",
            ),
            rabbitmq_publish_routing_key=os.getenv(
                "RABBITMQ_PUBLISH_ROUTING_KEY",
                "itinerary:provider_response",
            ),
            rabbitmq_debug_routing_key=os.getenv(
                "RABBITMQ_DEBUG_ROUTING_KEY",
                "debug:message",
            ),
            rabbitmq_status_routing_key=os.getenv(
                "RABBITMQ_STATUS_ROUTING_KEY",
                "status:message",
            ),
            rabbitmq_queue_name=os.getenv(
                "RABBITMQ_QUEUE_NAME",
                "inventory_hotel_service_verified_response_queue",
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
            amadeus_hotels_qps_limit=(
                float(os.getenv("AMADEUS_HOTELS_QPS_LIMIT", "0")) or None
            ),
            amadeus_429_max_attempts=int(os.getenv("AMADEUS_429_MAX_ATTEMPTS", "6")),
            amadeus_token_url=os.getenv(
                "AMADEUS_TOKEN_URL",
                "https://test.api.amadeus.com/v1/security/oauth2/token",
            ),
            amadeus_hotels_offers_limit=int(os.getenv("AMADEUS_HOTELS_OFFERS_LIMIT", "10")),
            amadeus_max_hotel_offers=_parse_amadeus_max_hotel_offers(),
            amadeus_hotels_citycode_radius_km=int(
                os.getenv("AMADEUS_HOTELS_CITYCODE_RADIUS_KM", "15")
            ),
            amadeus_hotels_latlng_radius_km=int(
                os.getenv("AMADEUS_HOTELS_LATLNG_RADIUS_KM", "5")
            ),
            amadeus_client_id=os.getenv("AMADEUS_CLIENT_ID", ""),
            amadeus_client_secret=os.getenv("AMADEUS_CLIENT_SECRET", ""),
        )

    @property
    def amqp_url(self) -> str:
        return (
            f"amqp://{self.amqp_user}:"
            f"{self.amqp_password}@{self.amqp_host}:{self.amqp_port}/"
        )
