#!/usr/bin/env python3
import asyncio
import json
import logging
import os
import pprint
import sys
from pathlib import Path
from typing import Any

PROJECT_DIR = Path(__file__).resolve().parent
SRC_DIR = PROJECT_DIR / "src"
ENV_FILE = PROJECT_DIR / ".env"
sys.path.insert(0, str(SRC_DIR))

import request_processor as request_processor_module  # noqa: E402
from amadeus_sender import AmadeusSender  # noqa: E402
from cfg import Cfg  # noqa: E402

logger = logging.getLogger("test_inventory_flight_service")


def _load_env_file(path: Path) -> None:
    if not path.exists():
        return

    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


async def _run_test() -> None:
    payload: dict[str, Any] = {
        "id": "req-test-001",
        "structured_response": {
            "request_id": "d38eedc3-977a-46ea-b59d-a09e30f108b8",
            "prompt_id": "resp_03a1bd9f25e178e40069a6d93fae848196910a89b09ab6e96d",
            "type": "valid_request",
            "output": {
                "trip": {
                    "timezone": "Europe/Zurich",
                    "travelers": 1,
                    "legs": [
                        {"from": "ZRH", "to": "BJS", "depart_date": "2026-04-12"},
                        {"from": "BJS", "to": "HKG", "depart_date": "2026-04-15"},
                        {"from": "HKG", "to": "SIN", "depart_date": "2026-04-17"},
                        {"from": "SIN", "to": "DEL", "depart_date": "2026-04-19"},
                        {"from": "DEL", "to": "ZRH", "depart_date": "2026-04-24"},
                    ],
                    "stays": [
                        {
                            "city": "Beijing",
                            "city_code": "BJS",
                            "location_latlng": {"lat": 39.901672, "lng": 116.4750221},
                            "check_in": "2026-04-12",
                            "check_out": "2026-04-15",
                            "min_rooms": 1,
                        },
                        {
                            "city": "Hong Kong",
                            "city_code": "HKG",
                            "check_in": "2026-04-15",
                            "check_out": "2026-04-17",
                            "min_rooms": 1,
                        },
                        {
                            "city": "Singapore",
                            "city_code": "SIN",
                            "check_in": "2026-04-17",
                            "check_out": "2026-04-19",
                            "min_rooms": 1,
                        },
                        {
                            "city": "New Delhi",
                            "city_code": "DEL",
                            "check_in": "2026-04-19",
                            "check_out": "2026-04-24",
                            "min_rooms": 1,
                        },
                    ],
                },
                "budgets": {
                    "flights": {"amount": 3000, "currency": "CHF", "scope": "total_trip"},
                    "hotels": {"amount": 300, "currency": "CHF", "scope": "per_night"},
                },
                "assumptions": [
                    "Interpreted dates in DD.MM.YYYY format; 12.03.2026 = 2026-03-12.",
                    "Assumed 1 traveler because number of travelers was not specified.",
                ],
                "missing_fields": [],
                "confidence": 0.84,
            },
        },
    }
    incoming_body = json.dumps(payload).encode("utf-8")

    cfg = Cfg.from_env()
    sender = AmadeusSender(cfg)
    results = await request_processor_module.process_incoming_message(
        sender, cfg, incoming_body
    )
    pprint.pprint(results)


if __name__ == "__main__":
    _load_env_file(ENV_FILE)
    asyncio.run(_run_test())
