"""Global cap on Amadeus API HTTP call rate (per service process)."""

from __future__ import annotations

import asyncio
from collections import deque


class AmadeusRequestRateLimit:
    """
    At most ``max_per_second`` HTTP calls per rolling 1.0s window.
    When the limit is reached, callers wait until a slot opens (asyncio.Lock + deque of timestamps).
    """

    __slots__ = ("_lock", "_max", "_timestamps")

    def __init__(self, max_per_second: int) -> None:
        if max_per_second <= 0:
            raise ValueError("max_per_second must be positive")
        self._max = int(max_per_second)
        self._lock = asyncio.Lock()
        self._timestamps: deque[float] = deque()

    async def acquire(self) -> None:
        while True:
            async with self._lock:
                now = asyncio.get_running_loop().time()
                while self._timestamps and self._timestamps[0] <= now - 1.0:
                    self._timestamps.popleft()
                if len(self._timestamps) < self._max:
                    self._timestamps.append(now)
                    return
                wait = self._timestamps[0] + 1.0 - now
            await asyncio.sleep(max(wait, 0.0))
