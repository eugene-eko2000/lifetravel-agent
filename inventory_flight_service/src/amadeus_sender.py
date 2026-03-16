import asyncio
from typing import Any

import httpx

from cfg import Cfg


class AmadeusSender:
    def __init__(self, cfg: Cfg | None = None) -> None:
        self._cfg = cfg or Cfg.from_env()
        self._bearer_token: str | None = None

    async def _get_amadeus_bearer_token(self) -> str:
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

    async def _authorized_request(
        self,
        method: str,
        url: str,
        *,
        params: dict[str, Any] | None = None,
        json_payload: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        merged_headers: dict[str, str] = {}
        if isinstance(headers, dict):
            merged_headers = {str(k): str(v) for k, v in headers.items()}

        token = await self._get_amadeus_bearer_token()
        merged_headers["Authorization"] = f"Bearer {token}"

        async with httpx.AsyncClient(timeout=30.0) as client:
            max_attempts = max(1, int(self._cfg.amadeus_429_max_attempts))
            backoff_seconds = 1.0
            last_response: httpx.Response | None = None
            for attempt in range(1, max_attempts + 1):
                response = await client.request(
                    method=method,
                    url=url,
                    params=params,
                    json=json_payload,
                    headers=merged_headers,
                )
                last_response = response

                if response.status_code == 401:
                    self._bearer_token = None
                    refreshed_token = await self._get_amadeus_bearer_token()
                    merged_headers["Authorization"] = f"Bearer {refreshed_token}"
                    response = await client.request(
                        method=method,
                        url=url,
                        params=params,
                        json=json_payload,
                        headers=merged_headers,
                    )
                    last_response = response

                if response.status_code == 429 and attempt < max_attempts:
                    await asyncio.sleep(backoff_seconds)
                    backoff_seconds *= 2.0
                    continue

                response.raise_for_status()
                return response.json()

            if last_response is not None:
                last_response.raise_for_status()
            raise ValueError("Amadeus request failed without response")

    async def send_flights_offers(
        self,
        payload: dict[str, Any],
        headers: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        return await self._authorized_request(
            "POST",
            self._cfg.amadeus_flights_offers_url,
            json_payload=payload,
            headers=headers,
        )
