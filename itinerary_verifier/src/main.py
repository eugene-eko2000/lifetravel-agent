import logging

import uvicorn
from fastapi import FastAPI

from cfg import Cfg

app = FastAPI(title="Itinerary Verifier Service")
logger = logging.getLogger("itinerary_verifier")


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    )
    cfg = Cfg.from_env()
    logger.info("Starting itinerary verifier service")
    uvicorn.run(app, host="0.0.0.0", port=cfg.endpoint_port)
