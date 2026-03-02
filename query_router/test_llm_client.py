#!/usr/bin/env python3
import argparse
import asyncio
import json
import os
import sys
import uuid
from pathlib import Path

# Allow running this script directly from the query_router directory.
PROJECT_DIR = Path(__file__).resolve().parent
SRC_DIR = PROJECT_DIR / "src"
ENV_FILE = PROJECT_DIR.parent / ".env"
sys.path.insert(0, str(SRC_DIR))

from llm_client import request_structured_itinerary  # noqa: E402


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

async def _run(text: str, request_id: str | None) -> None:
    rid = request_id or str(uuid.uuid4())
    response = await request_structured_itinerary(rid, None, text)
    print(json.dumps(response, indent=2))


def main() -> None:
    _load_env_file(ENV_FILE)

    parser = argparse.ArgumentParser(description="Test query_router LLM client")
    parser.add_argument("text", help="Input text to send to request_structured_itinerary")
    parser.add_argument(
        "--request-id",
        dest="request_id",
        default=None,
        help="Optional request id (auto-generated if omitted)",
    )
    args = parser.parse_args()

    asyncio.run(_run(args.text, args.request_id))


if __name__ == "__main__":
    main()
