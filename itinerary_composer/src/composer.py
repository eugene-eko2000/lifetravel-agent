import logging
from typing import Any

logger = logging.getLogger("itinerary_composer.composer")


async def compose_itinerary(payload: dict[str, Any]) -> dict[str, Any]:
    """Compose itinerary variants from the inventory response. Placeholder."""
    logger.info("compose_itinerary called (id=%s) — not yet implemented", payload.get("id"))
    return {"itineraries": []}
