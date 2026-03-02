import json
from typing import Optional

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, ValidationError

from rabbitmq_publisher import send_itinerary


class ItineraryRequest(BaseModel):
    id: Optional[str] = None
    content: str


app = FastAPI(title="Endpoint API")


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.websocket("/api/v1/itinerary")
async def itinerary_websocket(websocket: WebSocket) -> None:
    await websocket.accept()

    try:
        while True:
            raw_message = await websocket.receive_text()

            try:
                payload = json.loads(raw_message)
                request = ItineraryRequest.model_validate(payload)
            except json.JSONDecodeError:
                await websocket.send_json(
                    {
                        "error": "Invalid JSON payload",
                        "expected": {"id": "optional itinerary_id", "content": "user_prompt"},
                    }
                )
                continue
            except ValidationError as error:
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
        return
