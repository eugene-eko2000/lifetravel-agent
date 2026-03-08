import asyncio
import logging

import uvicorn
from fastapi import FastAPI

from cfg import Cfg
from rabbitmq_subscriber import run_ranking_subscriber

app = FastAPI(title="Ranking Service")
logger = logging.getLogger("ranking_service")
subscriber_task: asyncio.Task[None] | None = None


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.on_event("startup")
async def startup_event() -> None:
    global subscriber_task
    subscriber_task = asyncio.create_task(run_ranking_subscriber())
    logger.info("Ranking service started successfully")


@app.on_event("shutdown")
async def shutdown_event() -> None:
    if subscriber_task is not None:
        subscriber_task.cancel()
        try:
            await subscriber_task
        except asyncio.CancelledError:
            logger.info("Ranking subscriber task cancelled")


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    )
    cfg = Cfg.from_env()
    logger.info("Starting Ranking service on port %s", cfg.endpoint_port)
    uvicorn.run(app, host="0.0.0.0", port=cfg.endpoint_port)
