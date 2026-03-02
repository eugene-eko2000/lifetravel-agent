import asyncio
import logging

import uvicorn
from fastapi import FastAPI

from cfg import Cfg
from rabbitmq_router import run_router

logger = logging.getLogger("query_router")
app = FastAPI(title="Query Router")

router_task: asyncio.Task[None] | None = None


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.on_event("startup")
async def startup_event() -> None:
    global router_task
    router_task = asyncio.create_task(run_router())
    logger.info("Query Router started successfully")


@app.on_event("shutdown")
async def shutdown_event() -> None:
    if router_task is not None:
        router_task.cancel()
        try:
            await router_task
        except asyncio.CancelledError:
            logger.info("RabbitMQ router task cancelled on shutdown")


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    )
    cfg = Cfg.from_env()
    uvicorn.run(app, host="0.0.0.0", port=cfg.endpoint_port)
