import logging
from typing import Any, Awaitable, Callable

logger = logging.getLogger("inventory_hotel_service.debug_messages")

DebugPublisher = Callable[[dict[str, Any]], Awaitable[None]]


async def emit_debug_message(
    debug_publisher: DebugPublisher | None,
    request_id: str | None,
    message: str,
    *,
    level: str,
    payload: dict[str, Any] | None = None,
) -> None:
    if debug_publisher is None:
        return
    if not isinstance(request_id, str) or not request_id.strip():
        return
    debug_payload: dict[str, Any] = {
        "id": request_id,
        "level": level,
        "source": "inventory_hotel_service",
        "message": message,
    }
    if isinstance(payload, dict):
        debug_payload["payload"] = payload
    try:
        await debug_publisher(debug_payload)
    except Exception:
        logger.exception("Failed to publish debug message")
