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
    rabbitmq_debug_routing_key: str
    rabbitmq_publish_verified_message_routing_key: str
    rabbitmq_publish_adjusted_request_routing_key: str
    rabbitmq_queue_name: str
    openai_api_key: str
    openai_model: str
    openai_base_url: str

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
            rabbitmq_debug_routing_key=os.getenv(
                "RABBITMQ_DEBUG_ROUTING_KEY",
                "debug:message",
            ),
            rabbitmq_publish_verified_message_routing_key=os.getenv(
                "RABBITMQ_PUBLISH_VERIFIED_MESSAGE_ROUTING_KEY",
                "itinerary:verified_response",
            ),
            rabbitmq_publish_adjusted_request_routing_key=os.getenv(
                "RABBITMQ_PUBLISH_ADJUSTED_REQUEST_ROUTING_KEY",
                "itinerary:structured_request",
            ),
            rabbitmq_queue_name=os.getenv(
                "RABBITMQ_QUEUE_NAME",
                "itinerary_verifier_provider_response_queue",
            ),
            openai_api_key=os.getenv("OPENAI_API_KEY", ""),
            openai_model=os.getenv("OPENAI_MODEL", "gpt-5.2"),
            openai_base_url=os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1"),
        )

    @property
    def amqp_url(self) -> str:
        return (
            f"amqp://{self.amqp_user}:"
            f"{self.amqp_password}@{self.amqp_host}:{self.amqp_port}/"
        )
