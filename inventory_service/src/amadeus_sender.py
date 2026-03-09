from typing import Any

import httpx

from cfg import Cfg


class AmadeusSender:
    def __init__(self, cfg: Cfg | None = None) -> None:
        self._cfg = cfg or Cfg.from_env()
        self._bearer_token: str | None = None

    async def get_amadeus_bearer_token(self) -> str:
        if self._bearer_token:
            return self._bearer_token

        if not self._cfg.amadeus_client_id or not self._cfg.amadeus_client_secret:
            raise ValueError(
                "AMADEUS_CLIENT_ID and AMADEUS_CLIENT_SECRET must be set"
            )

        payload = {
            "grant_type": "client_credentials",
            "client_id": self._cfg.amadeus_client_id,
            "client_secret": self._cfg.amadeus_client_secret,
        }
        headers = {"Content-Type": "application/x-www-form-urlencoded"}

        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                self._cfg.amadeus_token_url,
                data=payload,
                headers=headers,
            )
            response.raise_for_status()
            token = response.json().get("access_token")
            if not isinstance(token, str) or not token:
                raise ValueError("Failed to retrieve Amadeus access token")
            self._bearer_token = token
            return token

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

    async def send_hotels_list_by_geocode(
        self,
        query_params: dict[str, Any],
        headers: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(
                self._cfg.amadeus_hotels_list_by_geocode_url,
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
