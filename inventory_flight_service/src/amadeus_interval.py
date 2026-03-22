"""Global minimum interval between Amadeus API HTTP calls (per service process)."""

from __future__ import annotations

import asyncio


class AmadeusQueryInterval:
    """Serializes Amadeus traffic: at least ``interval_seconds`` between consecutive queries."""

    __slots__ = ("_interval_sec", "_lock", "_next_allowed_ts")

    def __init__(self, interval_seconds: float) -> None:
        if interval_seconds <= 0:
            raise ValueError("interval_seconds must be positive")
        self._interval_sec = float(interval_seconds)
        self._lock = asyncio.Lock()
        self._next_allowed_ts = 0.0

    async def wait_before_query(self) -> None:
        async with self._lock:
            now = asyncio.get_running_loop().time()
            if now < self._next_allowed_ts:
                await asyncio.sleep(self._next_allowed_ts - now)
            now = asyncio.get_running_loop().time()
            self._next_allowed_ts = now + self._interval_sec
