#!/usr/bin/env python3
import asyncio
import json
import os
import requests
import sys
from pathlib import Path
from typing import Any

PROJECT_DIR = Path(__file__).resolve().parent
SRC_DIR = PROJECT_DIR / "src"
ENV_FILE = PROJECT_DIR / ".env"
sys.path.insert(0, str(SRC_DIR))

import rabbitmq_subscriber as subscriber_module  # noqa: E402
from amadeus_sender import AmadeusSender  # noqa: E402
from cfg import Cfg  # noqa: E402


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


def _get_amadeus_bearer_token():
    # curl "https://test.api.amadeus.com/v1/security/oauth2/token" \
    #  -H "Content-Type: application/x-www-form-urlencoded" \
    #  -d "grant_type=client_credentials&client_id=$AMADEUS_CLIENT_ID&client_secret=$AMADEUS_CLIENT_SECRET"

    client_id = os.getenv("AMADEUS_CLIENT_ID")
    client_secret = os.getenv("AMADEUS_CLIENT_SECRET")
    if not client_id or not client_secret:
        raise ValueError(
            "AMADEUS_CLIENT_ID and AMADEUS_CLIENT_SECRET must be set in env vars"
        )

    url = "https://test.api.amadeus.com/v1/security/oauth2/token"
    payload = {
        "grant_type": "client_credentials",
        "client_id": client_id,
        "client_secret": client_secret
    }
    headers = {
        "Content-Type": "application/x-www-form-urlencoded"
    }

    response = requests.post(url, data=payload, headers=headers)
    if response.status_code == 200:
        return response.json()["access_token"]
    else:
        raise ValueError(f"Failed to retrieve token: {response.status_code}")


async def _run_test() -> None:
    # Incoming payload shape that query_router/integration would send.
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
                        {
                            "from": "ZRH",
                            "to": "BJS",
                            "depart_date": "2026-03-12"
                        },
                        {
                            "from": "BJS",
                            "to": "HKG",
                            "depart_date": "2026-03-15"
                        },
                        {
                            "from": "HKG",
                            "to": "SIN",
                            "depart_date": "2026-03-17"
                        },
                        {
                            "from": "SIN",
                            "to": "DEL",
                            "depart_date": "2026-03-19"
                        },
                        {
                            "from": "DEL",
                            "to": "ZRH",
                            "depart_date": "2026-03-24"
                        }
                    ],
                    "stays": [
                        {
                            "city": "Beijing",
                            "city_code": "BJS",
                            "check_in": "2026-03-12",
                            "check_out": "2026-03-15",
                            "min_rooms": 1
                        },
                        {
                            "city": "Hong Kong",
                            "city_code": "HKG",
                            "check_in": "2026-03-15",
                            "check_out": "2026-03-17",
                            "min_rooms": 1
                        },
                        {
                            "city": "Singapore",
                            "city_code": "SIN",
                            "check_in": "2026-03-17",
                            "check_out": "2026-03-19",
                            "min_rooms": 1
                        },
                        {
                            "city": "New Delhi",
                            "city_code": "DEL",
                            "check_in": "2026-03-19",
                            "check_out": "2026-03-24",
                            "min_rooms": 1
                        }
                    ]
                },
                "budgets": {
                    "flights": {
                        "amount": 3000,
                        "currency": "CHF",
                        "scope": "total_trip"
                    },
                    "hotels": {
                        "amount": 300,
                        "currency": "CHF",
                        "scope": "per_night"
                    }
                },
                "assumptions": [
                    "Interpreted dates in DD.MM.YYYY format; 12.03.2026 = 2026-03-12.",
                    "Assumed 1 traveler because number of travelers was not specified.",
                    "Assumed each stay starts on arrival date and ends on the departure date of the next leg (no extra buffer days).",
                    "Used major city/metro airport codes (ZRH, BJS, HKG, SIN, DEL).",
                    "Hotel budget '300 CHF per day per person' mapped to 'per_night' and assumes 1 person."
                ],
                "missing_fields": [
                    "Number of travelers (affects hotel budget interpretation and rooms).",
                    "Preferred departure time windows for flights (optional).",
                    "Hotel requirements (rating, location/neighborhood, breakfast, etc.) if you have preferences (optional)."
                ],
                "confidence": 0.84
            }
        },
        "amadeus_headers": {"Authorization": f"Bearer {_get_amadeus_bearer_token()}"},
    }
    incoming_body = json.dumps(payload).encode("utf-8")

    cfg = Cfg.from_env()
    sender = AmadeusSender(cfg)
    results = await subscriber_module._process_incoming_message(sender, cfg, incoming_body)
    print(results)


if __name__ == "__main__":
    _load_env_file(ENV_FILE)
    asyncio.run(_run_test())
