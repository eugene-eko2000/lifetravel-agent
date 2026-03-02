import json
import logging
from typing import Optional

import uvicorn
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, ValidationError

from cfg import Cfg
from rabbitmq_publisher import send_itinerary

logger = logging.getLogger("endpoint_api")


class ItineraryRequest(BaseModel):
    id: Optional[str] = None
    content: str


app = FastAPI(title="Endpoint API")


@app.on_event("startup")
async def on_startup() -> None:
    cfg = Cfg.from_env()
    logger.info("Endpoint API started successfully on port %s", cfg.endpoint_port)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.websocket("/api/v1/itinerary")
async def itinerary_websocket(websocket: WebSocket) -> None:
    await websocket.accept()
    logger.info("WebSocket client connected to /api/v1/itinerary")

    try:
        while True:
            try:
                raw_message = await websocket.receive_text()
            except Exception:
                logger.exception("Error receiving WebSocket data")
                raise

            try:
                payload = json.loads(raw_message)
                request = ItineraryRequest.model_validate(payload)
            except json.JSONDecodeError:
                logger.warning("Invalid JSON payload received: %s", raw_message)
                await websocket.send_json(
                    {
                        "error": "Invalid JSON payload",
                        "expected": {"id": "optional itinerary_id", "content": "user_prompt"},
                    }
                )
                continue
            except ValidationError as error:
                logger.warning("Invalid itinerary request structure: %s", error)
                await websocket.send_json(
                    {
                        "error": "Invalid request structure",
                        "details": error.errors(),
                        "expected": {"id": "optional itinerary_id", "content": "user_prompt"},
                    }
                )
                continue

            try:
                await send_itinerary(request.model_dump())
            except Exception as error:  # noqa: BLE001
                logger.exception("Error processing itinerary request")
                await websocket.send_json(
                    {
                        "error": "Failed to publish itinerary request",
                        "details": str(error),
                    }
                )
                continue

            # Placeholder response. Business logic will be added later.
            await websocket.send_json(
                {
                    "id": request.id,
                    "content": request.content,
                    "status": "received",
                }
            )
    except WebSocketDisconnect:
        logger.info("WebSocket client disconnected")
        return
    except Exception:
        logger.exception("Unhandled error in itinerary WebSocket handler")
        return


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    )

    try:
        cfg = Cfg.from_env()
        logger.info("Starting Endpoint API service on port %s", cfg.endpoint_port)
        uvicorn.run(app, host="0.0.0.0", port=cfg.endpoint_port)
    except Exception:
        logger.exception("Service failed to start")
        raise
