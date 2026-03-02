import uvicorn
from fastapi import FastAPI

from cfg import Cfg

app = FastAPI(title="Inventory Service")


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


if __name__ == "__main__":
    cfg = Cfg.from_env()
    uvicorn.run(app, host="0.0.0.0", port=cfg.endpoint_port)
