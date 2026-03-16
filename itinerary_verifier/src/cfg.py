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
    rabbitmq_publish_verified_message_routing_key: str
    rabbitmq_publish_adjusted_request_routing_key: str
    rabbitmq_queue_name: str

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
                "itinerary:provider_response",
            ),
            rabbitmq_publish_verified_message_routing_key=os.getenv(
                "RABBITMQ_PUBLISH_VERIFIED_MESSAGE_ROUTING_KEY",
                "itinerary:verified_response",
            ),
            rabbitmq_publish_adjusted_request_routing_key=os.getenv(
                "RABBITMQ_PUBLISH_ADJUSTED_REQUEST_ROUTING_KEY",
                "itinerary:user_request",
            ),
            rabbitmq_queue_name=os.getenv(
                "RABBITMQ_QUEUE_NAME",
                "itinerary_verifier_provider_response_queue",
            ),
        )

    @property
    def amqp_url(self) -> str:
        return (
            f"amqp://{self.amqp_user}:"
            f"{self.amqp_password}@{self.amqp_host}:{self.amqp_port}/"
        )
