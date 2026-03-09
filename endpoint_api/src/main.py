import json
import logging
import asyncio
from dataclasses import dataclass, field
from typing import Optional
from uuid import uuid4

import uvicorn
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, ValidationError

from cfg import Cfg
from rabbitmq_publisher import send_itinerary
from rabbitmq_subscriber import (
    run_debug_subscriber,
    run_missing_info_subscriber,
    run_ranked_subscriber,
)

logger = logging.getLogger("endpoint_api")


class ItineraryRequest(BaseModel):
    id: Optional[str] = None
    prompt_id: Optional[str] = None
    content: str


app = FastAPI(title="Endpoint API")


@dataclass
class ClientSession:
    websocket: WebSocket
    send_lock: asyncio.Lock = field(default_factory=asyncio.Lock)


class ConnectionManager:
    def __init__(self) -> None:
        self._sessions: dict[int, ClientSession] = {}
        self._request_owner: dict[str, int] = {}
        self._lock = asyncio.Lock()

    async def connect(self, websocket: WebSocket) -> int:
        session_id = id(websocket)
        async with self._lock:
            self._sessions[session_id] = ClientSession(websocket=websocket)
        return session_id

    async def disconnect(self, session_id: int) -> None:
        async with self._lock:
            self._sessions.pop(session_id, None)
            request_ids = [
                request_id
                for request_id, owner in self._request_owner.items()
                if owner == session_id
            ]
            for request_id in request_ids:
                self._request_owner.pop(request_id, None)

    async def bind_request(self, request_id: str, session_id: int) -> None:
        async with self._lock:
            self._request_owner[request_id] = session_id

    async def unbind_request(self, request_id: str) -> None:
        async with self._lock:
            self._request_owner.pop(request_id, None)

    async def send_to_request(self, request_id: str, payload: dict) -> bool:
        async with self._lock:
            session_id = self._request_owner.get(request_id)
            session = self._sessions.get(session_id) if session_id is not None else None

        if session is None:
            return False

        async with session.send_lock:
            await session.websocket.send_json(payload)
        return True

    async def send_to_session(self, session_id: int, payload: dict) -> bool:
        async with self._lock:
            session = self._sessions.get(session_id)

        if session is None:
            return False

        async with session.send_lock:
            await session.websocket.send_json(payload)
        return True


connection_manager = ConnectionManager()


async def _handle_missing_info_message(payload: dict) -> None:
    request_id = payload.get("id")
    structured_response = payload.get("structured_response")
    if not isinstance(request_id, str) or not request_id.strip():
        logger.warning("Missing-info message without valid id: %s", payload)
        return
    if not isinstance(structured_response, dict):
        logger.warning("Missing-info message without structured_response: %s", payload)
        return

    message = {
        "type": "missing_info",
        "id": request_id,
        "structured_response": structured_response,
    }

    delivered = await connection_manager.send_to_request(request_id, message)
    if delivered:
        logger.info("Delivered missing_info message to websocket for id=%s", request_id)
    else:
        logger.warning("No active websocket mapping for missing_info id=%s", request_id)


async def _handle_ranked_message(payload: dict) -> None:
    request_id = payload.get("id")
    ranked_response = payload.get("ranked_response")
    if not isinstance(request_id, str) or not request_id.strip():
        logger.warning("Ranked message without valid id: %s", payload)
        return
    if not isinstance(ranked_response, dict):
        logger.warning("Ranked message without ranked_response: %s", payload)
        return

    message = {
        "type": "ranked",
        "id": request_id,
        "ranked_response": ranked_response,
    }

    delivered = await connection_manager.send_to_request(request_id, message)
    if delivered:
        logger.info("Delivered ranked itinerary to websocket for id=%s", request_id)
    else:
        logger.warning("No active websocket mapping for ranked id=%s", request_id)


async def _handle_debug_message(payload: dict) -> None:
    request_id = payload.get("id")
    if not isinstance(request_id, str) or not request_id.strip():
        request_id = payload.get("request_id")
    if not isinstance(request_id, str) or not request_id.strip():
        logger.warning("Debug message without valid request id: %s", payload)
        return

    payload["type"] = "debug"
    delivered = await connection_manager.send_to_request(request_id, payload)
    if delivered:
        logger.info("Delivered debug message to itinerary websocket for id=%s", request_id)
    else:
        logger.warning("No active itinerary websocket mapping for debug id=%s", request_id)


@app.on_event("startup")
async def on_startup() -> None:
    cfg = Cfg.from_env()
    logger.info("Endpoint API started successfully on port %s", cfg.endpoint_port)
    app.state.missing_info_task = asyncio.create_task(
        run_missing_info_subscriber(_handle_missing_info_message)
    )
    app.state.ranked_task = asyncio.create_task(
        run_ranked_subscriber(_handle_ranked_message)
    )
    app.state.debug_task = asyncio.create_task(
        run_debug_subscriber(_handle_debug_message)
    )


@app.on_event("shutdown")
async def on_shutdown() -> None:
    missing_info_task = getattr(app.state, "missing_info_task", None)
    ranked_task = getattr(app.state, "ranked_task", None)
    debug_task = getattr(app.state, "debug_task", None)
    for name, task in (
        ("missing-info", missing_info_task),
        ("ranked", ranked_task),
        ("debug", debug_task),
    ):
        if task is None:
            continue
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            logger.info("%s subscriber task cancelled", name)
        except Exception:
            logger.exception("%s subscriber task failed during shutdown", name)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.websocket("/api/v1/itinerary")
async def itinerary_websocket(websocket: WebSocket) -> None:
    await websocket.accept()
    session_id = await connection_manager.connect(websocket)
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
                await connection_manager.send_to_session(
                    session_id,
                    {
                        "error": "Invalid JSON payload",
                        "expected": {"id": "optional itinerary_id", "content": "user_prompt"},
                    }
                )
                continue
            except ValidationError as error:
                logger.warning("Invalid itinerary request structure: %s", error)
                await connection_manager.send_to_session(
                    session_id,
                    {
                        "error": "Invalid request structure",
                        "details": error.errors(),
                        "expected": {"id": "optional itinerary_id", "content": "user_prompt"},
                    }
                )
                continue

            request_id: Optional[str] = None
            try:
                outgoing_payload = request.model_dump()
                request_id = outgoing_payload.get("id")
                if not isinstance(request_id, str) or not request_id.strip():
                    request_id = str(uuid4())
                    outgoing_payload["id"] = request_id

                await connection_manager.bind_request(request_id, session_id)
                await send_itinerary(outgoing_payload)
            except Exception as error:  # noqa: BLE001
                logger.exception("Error processing itinerary request")
                if isinstance(request_id, str) and request_id:
                    await connection_manager.unbind_request(request_id)
                await connection_manager.send_to_session(
                    session_id,
                    {
                        "error": "Failed to publish itinerary request",
                        "details": str(error),
                    }
                )
                continue

            # Placeholder response. Business logic will be added later.
            await connection_manager.send_to_session(
                session_id,
                {
                    "id": request_id,
                    "content": request.content,
                    "status": "received",
                }
            )
    except WebSocketDisconnect:
        logger.info("WebSocket client disconnected")
        await connection_manager.disconnect(session_id)
        return
    except Exception:
        logger.exception("Unhandled error in itinerary WebSocket handler")
        await connection_manager.disconnect(session_id)
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
