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
    rabbitmq_publish_routing_key: str
    rabbitmq_debug_routing_key: str
    rabbitmq_queue_name: str
    amadeus_flights_offers_url: str
    amadeus_flights_qps_limit: float | None
    amadeus_token_url: str
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
                "itinerary:structured_request",
            ),
            rabbitmq_publish_routing_key=os.getenv(
                "RABBITMQ_PUBLISH_ROUTING_KEY",
                "itinerary:provider_flight_response",
            ),
            rabbitmq_debug_routing_key=os.getenv(
                "RABBITMQ_DEBUG_ROUTING_KEY",
                "debug:message",
            ),
            rabbitmq_queue_name=os.getenv(
                "RABBITMQ_QUEUE_NAME",
                "inventory_flight_service_structured_request_queue",
            ),
            amadeus_flights_offers_url=os.getenv(
                "AMADEUS_FLIGHTS_OFFERS_URL",
                "https://test.api.amadeus.com/v2/shopping/flight-offers",
            ),
            amadeus_flights_qps_limit=(
                float(os.getenv("AMADEUS_FLIGHTS_QPS_LIMIT", "0")) or None
            ),
            amadeus_token_url=os.getenv(
                "AMADEUS_TOKEN_URL",
                "https://test.api.amadeus.com/v1/security/oauth2/token",
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
