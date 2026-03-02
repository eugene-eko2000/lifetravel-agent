from typing import Any

import httpx

from cfg import Cfg


class AmadeusSender:
    def __init__(self, cfg: Cfg | None = None) -> None:
        self._cfg = cfg or Cfg.from_env()

    async def send_flights_offers(
        self,
        payload: dict[str, Any],
        headers: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                self._cfg.amadeus_flights_offers_url,
                json=payload,
                headers=headers,
            )
            response.raise_for_status()
            return response.json()

    async def send_hotels_list(
        self,
        query_params: dict[str, Any],
        headers: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(
                self._cfg.amadeus_hotels_list_url,
                params=query_params,
                headers=headers,
            )
            response.raise_for_status()
            return response.json()

    async def send_hotels_offers(
        self,
        query_params: dict[str, Any],
        headers: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(
                self._cfg.amadeus_hotels_offers_url,
                params=query_params,
                headers=headers,
            )
            response.raise_for_status()
            return response.json()
